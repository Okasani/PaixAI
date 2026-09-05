from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from typing import Any, Protocol

from app.avatar.live2d import Live2DAvatarAdapter
from app.events.schemas import RealtimeEvent


class EventSink(Protocol):
    async def send_json(self, event: dict[str, Any]) -> None: ...


class AvatarPublisher(Protocol):
    async def publish(self, event: dict[str, Any]) -> None: ...


class AvatarEventFanout:
    """Preserve the primary stream while publishing sanitized avatar commands."""

    def __init__(self, primary: EventSink, adapter: Live2DAvatarAdapter, publisher: AvatarPublisher) -> None:
        self.primary = primary
        self.adapter = adapter
        self.publisher = publisher

    async def send_json(self, event: dict[str, Any]) -> None:
        await self.primary.send_json(event)
        command = self.adapter.transform(event)
        if command is not None:
            await self.publisher.publish(command)


class Live2DStageServer:
    """Loopback-only, read-only WebSocket stream for the desktop stage."""

    def __init__(self, *, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._server: Any | None = None
        self._clients: set[Any] = set()
        self._latest: dict[str, dict[str, Any]] = {}

    @property
    def url(self) -> str:
        display_host = "127.0.0.1" if self.host == "localhost" else self.host
        return f"ws://{display_host}:{self.port}"

    async def start(self) -> None:
        try:
            from websockets.asyncio.server import serve
        except ImportError as exc:
            raise RuntimeError("The Live2D stage stream requires the backend websockets dependency") from exc
        self._server = await serve(
            self._handle,
            self.host,
            self.port,
            max_size=4096,
            max_queue=4,
            ping_interval=20,
            ping_timeout=20,
        )
        if self.port == 0 and self._server.sockets:
            self.port = int(self._server.sockets[0].getsockname()[1])

    async def _handle(self, websocket: Any) -> None:
        self._clients.add(websocket)
        try:
            for event in sorted(self._latest.values(), key=lambda item: int(item["sequence"])):
                await websocket.send(json.dumps(event, separators=(",", ":")))
            async for _message in websocket:
                await websocket.close(code=1008, reason="The avatar stream is read-only")
                break
        finally:
            self._clients.discard(websocket)

    async def publish(self, event: dict[str, Any]) -> None:
        validated = RealtimeEvent.model_validate(event)
        if not validated.type.startswith("avatar."):
            raise ValueError("The stage stream accepts avatar commands only")
        wire = validated.wire()
        self._latest[validated.type] = wire
        if not self._clients:
            return
        message = json.dumps(wire, separators=(",", ":"))
        clients = list(self._clients)
        results: list[Any] = await asyncio.gather(
            *(client.send(message) for client in clients),
            return_exceptions=True,
        )
        for client, result in zip(clients, results, strict=True):
            if isinstance(result, BaseException):
                self._clients.discard(client)

    async def close(self) -> None:
        clients = list(self._clients)
        if clients:
            await asyncio.gather(*(self._close_client(client) for client in clients), return_exceptions=True)
        self._clients.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @staticmethod
    def _close_client(client: Any) -> Awaitable[Any]:
        return client.close(code=1001, reason="Paix voice runtime stopped")
