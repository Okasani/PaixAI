from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__
from app.api import api_router
from app.core.config import get_settings
from app.core.db import init_db
from app.core.logging import configure_redacted_logging
from app.core.runtime import build_runtime
from app.events.schemas import ClientEvent

settings = get_settings()
configure_redacted_logging(settings.log_level)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        length = request.headers.get("content-length")
        if length:
            try:
                too_large = int(length) > settings.max_request_bytes and not request.url.path.endswith(
                    "/stt/transcribe"
                )
            except ValueError:
                too_large = True
            if too_large:
                return JSONResponse(status_code=413, content={"detail": "Request exceeds the configured size limit"})
        return await call_next(request)


runtime = build_runtime(settings)


@asynccontextmanager
async def lifespan(application: FastAPI):
    await init_db()
    application.state.runtime = runtime
    yield
    for connection in list(runtime.orchestrator.connections.values()):
        await runtime.orchestrator.disconnect(connection)


app = FastAPI(
    title="Paix Backend",
    version=__version__,
    description="Local-first modular realtime AI companion API",
    lifespan=lifespan,
)
app.state.runtime = runtime
app.add_middleware(RequestSizeLimitMiddleware)
app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def backend_landing() -> dict[str, str]:
    """Make an accidental visit to the optional developer API self-explanatory."""
    return {
        "name": settings.app_name,
        "status": "ok",
        "primary_interface": "python -m app.voice.cli",
        "health": "/api/health",
        "docs": "/docs",
    }


@app.exception_handler(Exception)
async def unhandled_exception(_: Request, exception: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_type": type(exception).__name__},
    )


@app.websocket("/ws/chat")
async def chat_socket(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.allowed_websocket_origins:
        await websocket.close(code=1008, reason="Origin is not allowed")
        return
    await websocket.accept()
    initial_session_id = websocket.query_params.get("session_id") or f"pending-{uuid.uuid4()}"
    connection = await runtime.orchestrator.connect(websocket, initial_session_id)
    try:
        while True:
            raw = await websocket.receive_json()
            try:
                event = ClientEvent.model_validate(raw)
            except ValidationError as exc:
                turn_id = str(raw.get("turn_id") or "validation") if isinstance(raw, dict) else "validation"
                await connection.send(
                    "websocket.error",
                    turn_id,
                    {
                        "code": "validation_error",
                        "message": "Invalid realtime event",
                        "details": exc.errors(include_input=False),
                    },
                )
                continue
            if connection.session_id.startswith("pending-"):
                connection.session_id = event.session_id
            elif event.session_id != connection.session_id:
                await connection.send(
                    "websocket.error",
                    event.turn_id or "validation",
                    {"message": "session_id changed on an active socket"},
                )
                continue
            turn_id = event.turn_id or str(uuid.uuid4())
            if event.type == "chat.send":
                await runtime.orchestrator.start_turn(connection, turn_id, event.payload)
            elif event.type == "turn.cancel":
                await runtime.orchestrator.cancel_active(connection, "user_requested")
            elif event.type in {"audio.start", "speech.started", "barge_in"}:
                await runtime.orchestrator.cancel_active(connection, "voice_barge_in")
                await connection.send("turn.state", turn_id, {"state": "listening"})
            elif event.type == "audio.chunk":
                await runtime.orchestrator.audio_chunk(connection, turn_id, event.payload)
            elif event.type == "audio.vad_chunk":
                await runtime.orchestrator.vad_chunk(connection, turn_id, event.payload)
            elif event.type == "audio.commit":
                await runtime.orchestrator.audio_commit(connection, turn_id, event.payload)
            elif event.type == "ping":
                await connection.send("pong", turn_id, {})
            else:
                await connection.send(
                    "websocket.error",
                    turn_id,
                    {"code": "unknown_event", "message": f"Unknown event type: {event.type}"},
                )
    except WebSocketDisconnect:
        pass
    finally:
        await runtime.orchestrator.disconnect(connection)
