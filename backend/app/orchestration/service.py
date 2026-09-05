from __future__ import annotations

import asyncio
import base64
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from app.core.config import Settings
from app.core.db import AsyncSessionLocal
from app.core.models import Conversation, LatencyEvent, Message, ProviderUsage
from app.core.security import redact
from app.events.schemas import RealtimeEvent
from app.memory.service import MemoryService
from app.persona.context_builder import ContextBuilder
from app.persona.emotions import EmotionalStateService
from app.providers.llm.base import (
    CancellationToken,
    CanonicalLLMRequest,
    CanonicalMessage,
    CanonicalToolDefinition,
)
from app.providers.llm.registry import ProviderRegistry
from app.speech.phrase_chunker import PhraseChunker, PhraseChunkerConfig
from app.speech.stt import FasterWhisperSTT, SileroVADSession
from app.speech.tts import ElevenLabsTTS
from app.tools.registry import ToolRegistry


class RealtimeEventSink(Protocol):
    async def send_json(self, event: dict[str, Any]) -> None: ...


@dataclass
class ActiveTurn:
    turn_id: str
    cancellation: CancellationToken
    task: asyncio.Task[None] | None = None
    started_at: float = field(default_factory=time.perf_counter)


@dataclass
class ConnectionSession:
    session_id: str
    websocket: RealtimeEventSink
    sequence: int = 0
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    state_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active: ActiveTurn | None = None
    audio_buffers: dict[str, bytearray] = field(default_factory=dict)
    vad_sessions: dict[str, SileroVADSession] = field(default_factory=dict)
    unavailable_vad_turns: set[str] = field(default_factory=set)

    async def send(self, event_type: str, turn_id: str, payload: dict[str, Any] | None = None) -> None:
        async with self.send_lock:
            self.sequence += 1
            event = RealtimeEvent(
                type=event_type,
                session_id=self.session_id,
                turn_id=turn_id,
                sequence=self.sequence,
                timestamp=datetime.now(UTC),
                payload=redact(payload or {}),
            )
            await self.websocket.send_json(event.wire())


class RealtimeOrchestrator:
    def __init__(
        self,
        *,
        settings: Settings,
        providers: ProviderRegistry,
        context_builder: ContextBuilder,
        emotions: EmotionalStateService,
        memories: MemoryService,
        tts: ElevenLabsTTS,
        stt: FasterWhisperSTT,
        tools: ToolRegistry,
    ) -> None:
        self.settings = settings
        self.providers = providers
        self.context_builder = context_builder
        self.emotions = emotions
        self.memories = memories
        self.tts = tts
        self.stt = stt
        self.tools = tools
        self.connections: dict[int, ConnectionSession] = {}

    async def connect(self, websocket: RealtimeEventSink, session_id: str) -> ConnectionSession:
        connection = ConnectionSession(session_id=session_id, websocket=websocket)
        self.connections[id(websocket)] = connection
        await connection.send(
            "session.ready",
            "system",
            {"state": "idle", "providers": [provider.provider_id for provider in self.providers.all()]},
        )
        return connection

    async def disconnect(self, connection: ConnectionSession) -> None:
        async with connection.state_lock:
            if connection.active:
                connection.active.cancellation.cancel()
                if connection.active.task:
                    connection.active.task.cancel()
            connection.active = None
        self.connections.pop(id(connection.websocket), None)

    async def cancel_active(self, connection: ConnectionSession, reason: str = "user_requested") -> None:
        async with connection.state_lock:
            await self._cancel_locked(connection, reason)

    async def _cancel_locked(self, connection: ConnectionSession, reason: str) -> None:
        active = connection.active
        if active is None:
            return
        connection.active = None
        active.cancellation.cancel()
        if active.task and active.task is not asyncio.current_task():
            active.task.cancel()
        await connection.send("response.cancelled", active.turn_id, {"reason": reason})
        await connection.send("audio.cancelled", active.turn_id, {"reason": reason})
        await connection.send("turn.state", active.turn_id, {"state": "idle", "reason": reason})

    async def start_turn(self, connection: ConnectionSession, turn_id: str, payload: dict[str, Any]) -> None:
        text = str(payload.get("text", "")).strip()
        if not text:
            await connection.send(
                "provider.error", turn_id, {"code": "validation_error", "message": "Message text is empty"}
            )
            return
        if len(text) > 100_000:
            await connection.send(
                "provider.error", turn_id, {"code": "validation_error", "message": "Message is too large"}
            )
            return
        async with connection.state_lock:
            await self._cancel_locked(connection, "barge_in_new_turn")
            active = ActiveTurn(turn_id=turn_id, cancellation=CancellationToken())
            connection.active = active
            active.task = asyncio.create_task(self._run_turn(connection, active, payload))

    def _is_current(self, connection: ConnectionSession, turn: ActiveTurn) -> bool:
        return connection.active is turn and not turn.cancellation.cancelled

    def _default_model(self, provider_id: str) -> str:
        return {
            "mock": self.settings.mock_model,
            "local": self.settings.local_model,
            "openai": self.settings.openai_model,
            "anthropic": self.settings.anthropic_model,
            "openrouter": self.settings.openrouter_model,
        }.get(provider_id, "")

    async def _ensure_conversation(self, session: Any, requested: str | None, text: str) -> Conversation:
        conversation = await session.get(Conversation, requested) if requested else None
        if conversation is None:
            conversation = Conversation(id=requested or str(uuid.uuid4()), title=text[:80] or "New conversation")
            session.add(conversation)
            await session.commit()
            await session.refresh(conversation)
        return conversation

    async def _emit_metric(
        self,
        connection: ConnectionSession,
        turn: ActiveTurn,
        conversation_id: str,
        name: str,
        duration_ms: float,
        details: dict[str, Any] | None = None,
    ) -> None:
        if not self._is_current(connection, turn):
            return
        await connection.send(
            "pipeline.metric", turn.turn_id, {"name": name, "duration_ms": duration_ms, **(details or {})}
        )
        async with AsyncSessionLocal() as database:
            database.add(
                LatencyEvent(
                    conversation_id=conversation_id,
                    turn_id=turn.turn_id,
                    name=name,
                    duration_ms=duration_ms,
                    details_json=details or {},
                )
            )
            await database.commit()

    async def _tts_worker(
        self,
        connection: ConnectionSession,
        turn: ActiveTurn,
        queue: asyncio.Queue[str | None],
        voice_id: str,
        model_id: str,
        output_format: str,
        voice_settings: dict[str, Any],
        llm_started: float,
        conversation_id: str,
    ) -> None:
        async def text_stream():
            while not turn.cancellation.cancelled:
                item = await queue.get()
                if item is None:
                    return
                await connection.send("tts.phrase", turn.turn_id, {"characters": len(item), "text": item})
                yield item

        first_audio = True
        try:
            async for chunk in self.tts.stream_audio(
                text_stream(),
                turn.cancellation,
                voice_id=voice_id,
                model_id=model_id,
                output_format=output_format,
                voice_settings=voice_settings,
            ):
                if not self._is_current(connection, turn):
                    return
                if first_audio and chunk.audio_base64:
                    first_audio = False
                    elapsed = (time.perf_counter() - llm_started) * 1000
                    await connection.send("turn.state", turn.turn_id, {"state": "speaking"})
                    await self._emit_metric(
                        connection, turn, conversation_id, "time_to_first_audio", elapsed, {"provider": "elevenlabs"}
                    )
                await connection.send(
                    "tts.audio",
                    turn.turn_id,
                    {
                        "audio_base64": chunk.audio_base64,
                        "base64": chunk.audio_base64,
                        "output_format": chunk.output_format,
                        "mime_type": "audio/pcm" if chunk.output_format.startswith("pcm") else "audio/mpeg",
                        "sample_rate": chunk.sample_rate,
                        "is_final": chunk.is_final,
                        "alignment": chunk.alignment,
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._is_current(connection, turn):
                await connection.send(
                    "tts.error", turn.turn_id, {"code": type(exc).__name__, "message": str(exc)[:500]}
                )

    async def _run_turn(self, connection: ConnectionSession, turn: ActiveTurn, payload: dict[str, Any]) -> None:
        text = str(payload["text"]).strip()
        provider_id = str(payload.get("provider_id") or self.settings.default_provider)
        model_id = str(payload.get("model_id") or self._default_model(provider_id))
        options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        raw_events = bool(payload.get("raw_events", False))
        try:
            provider = self.providers.get(provider_id)
        except KeyError:
            await connection.send(
                "provider.error",
                turn.turn_id,
                {"code": "unknown_provider", "message": f"Unknown provider: {provider_id}"},
            )
            connection.active = None
            return

        llm_started = time.perf_counter()
        tts_task: asyncio.Task[None] | None = None
        phrase_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=32)
        chunker = PhraseChunker(
            PhraseChunkerConfig(
                first_min_chars=int(payload.get("tts_first_min_chars", 36)),
                min_chars=int(payload.get("tts_min_chars", 64)),
                max_chars=int(payload.get("tts_max_chars", 180)),
            )
        )
        assistant_text = ""
        usage: dict[str, Any] = {}
        first_token = True
        completed = False
        conversation_id = ""
        user_message_id = ""
        try:
            await connection.send("turn.state", turn.turn_id, {"state": "thinking"})
            async with AsyncSessionLocal() as database:
                conversation = await self._ensure_conversation(database, payload.get("conversation_id"), text)
                conversation_id = conversation.id
                emotional_snapshot = await self.emotions.update_for_message(database, text)
                context_started = time.perf_counter()
                inspection = await self.context_builder.build(
                    database,
                    conversation_id=conversation.id,
                    current_user_message=text,
                    tool_results=payload.get("tool_results") if isinstance(payload.get("tool_results"), list) else [],
                )
                context_ms = (time.perf_counter() - context_started) * 1000
                user_message = Message(
                    conversation_id=conversation.id,
                    turn_id=turn.turn_id,
                    role="user",
                    content=text,
                    metadata_json={"source": payload.get("source", "typed")},
                )
                database.add(user_message)
                await database.commit()
                await database.refresh(user_message)
                user_message_id = user_message.id
            if not self._is_current(connection, turn):
                return
            await connection.send(
                "emotion.state",
                turn.turn_id,
                {"values": emotional_snapshot.values.model_dump(mode="json")},
            )
            await connection.send(
                "prompt.compiled",
                turn.turn_id,
                {
                    **inspection.model_dump(mode="json"),
                    "conversation_id": conversation_id,
                    "context_assembly_ms": context_ms,
                },
            )
            await self._emit_metric(connection, turn, conversation_id, "context_assembly", context_ms)

            voice_enabled = bool(payload.get("voice_enabled", False))
            voice_id = str(payload.get("voice_id") or self.settings.elevenlabs_voice_id or "")
            if voice_enabled and voice_id and self.tts.configured():
                voice_settings = (
                    payload.get("voice_settings") if isinstance(payload.get("voice_settings"), dict) else {}
                )
                tts_task = asyncio.create_task(
                    self._tts_worker(
                        connection,
                        turn,
                        phrase_queue,
                        voice_id,
                        str(payload.get("voice_model") or self.settings.elevenlabs_model_id),
                        str(payload.get("output_format") or self.settings.elevenlabs_output_format),
                        voice_settings,
                        llm_started,
                        conversation_id,
                    )
                )
            elif voice_enabled:
                await connection.send(
                    "tts.skipped",
                    turn.turn_id,
                    {"reason": "Select a voice and configure ELEVENLABS_API_KEY to enable speech"},
                )

            definitions = [
                CanonicalToolDefinition(name=tool.name, description=tool.description, input_schema=tool.input_schema)
                for tool in self.tools.manifests()
            ]
            request = CanonicalLLMRequest(
                model=model_id,
                system_prompt=inspection.final_prompt,
                messages=inspection.recent_turns
                + [CanonicalMessage(role="user", content=inspection.current_user_message)],
                tools=definitions,
                options=options,
                metadata={"conversation_id": conversation_id, "turn_id": turn.turn_id},
            )
            async for provider_event in provider.stream_response(request, turn.cancellation):
                if not self._is_current(connection, turn):
                    return
                event_payload = dict(provider_event.payload)
                if raw_events and provider_event.raw is not None:
                    event_payload["raw"] = redact(provider_event.raw)
                if provider_event.type == "response.started":
                    event_payload["conversation_id"] = conversation_id
                    event_payload.setdefault("provider", provider_id)
                    event_payload.setdefault("model", model_id)
                elif provider_event.type == "text.delta":
                    delta = str(event_payload.get("text", ""))
                    assistant_text += delta
                    if first_token and delta:
                        first_token = False
                        await self._emit_metric(
                            connection,
                            turn,
                            conversation_id,
                            "time_to_first_llm_token",
                            (time.perf_counter() - llm_started) * 1000,
                            {"provider": provider_id, "model": model_id},
                        )
                    if tts_task:
                        for phrase in chunker.feed(delta):
                            await phrase_queue.put(phrase)
                elif provider_event.type == "usage.updated":
                    usage.update(event_payload)
                elif provider_event.type == "response.completed":
                    completed = True
                await connection.send(provider_event.type, turn.turn_id, event_payload)

            if tts_task:
                for phrase in chunker.flush():
                    await phrase_queue.put(phrase)
                await phrase_queue.put(None)
                await tts_task

            if not self._is_current(connection, turn):
                return
            async with AsyncSessionLocal() as database:
                if assistant_text:
                    database.add(
                        Message(
                            conversation_id=conversation_id,
                            turn_id=turn.turn_id,
                            role="assistant",
                            content=assistant_text,
                            provider_id=provider_id,
                            model_id=model_id,
                            metadata_json={"completed": completed},
                        )
                    )
                database.add(
                    ProviderUsage(
                        conversation_id=conversation_id,
                        turn_id=turn.turn_id,
                        provider_id=provider_id,
                        model_id=model_id,
                        input_tokens=int(usage.get("input_tokens", 0) or 0),
                        output_tokens=int(usage.get("output_tokens", 0) or 0),
                        tts_characters=len(assistant_text) if tts_task else 0,
                        estimated_cost_usd=usage.get("cost_usd"),
                    )
                )
                await database.commit()
            asyncio.create_task(self._extract_candidate(user_message_id, text))
            await self._emit_metric(
                connection,
                turn,
                conversation_id,
                "total_turn_latency",
                (time.perf_counter() - llm_started) * 1000,
            )
            await connection.send("turn.state", turn.turn_id, {"state": "idle"})
        except asyncio.CancelledError:
            if tts_task:
                tts_task.cancel()
                await asyncio.gather(tts_task, return_exceptions=True)
            raise
        except Exception as exc:
            if self._is_current(connection, turn):
                await connection.send(
                    "provider.error", turn.turn_id, {"code": type(exc).__name__, "message": str(exc)[:500]}
                )
                await connection.send("turn.state", turn.turn_id, {"state": "error"})
        finally:
            async with connection.state_lock:
                if connection.active is turn:
                    connection.active = None

    async def _extract_candidate(self, message_id: str, text: str) -> None:
        try:
            async with AsyncSessionLocal() as database:
                await self.memories.extract_candidate(database, message_id, text)
        except Exception:
            return

    async def audio_chunk(self, connection: ConnectionSession, turn_id: str, payload: dict[str, Any]) -> None:
        encoded = payload.get("audio_base64") or payload.get("base64")
        if not isinstance(encoded, str):
            await connection.send("stt.error", turn_id, {"message": "audio_base64 is required"})
            return
        try:
            data = base64.b64decode(encoded, validate=True)
        except Exception:
            await connection.send("stt.error", turn_id, {"message": "Invalid base64 audio"})
            return
        buffer = connection.audio_buffers.setdefault(turn_id, bytearray())
        if len(buffer) + len(data) > self.settings.max_audio_bytes:
            connection.audio_buffers.pop(turn_id, None)
            await connection.send("stt.error", turn_id, {"message": "Audio buffer limit exceeded"})
            return
        buffer.extend(data)
        await connection.send("audio.buffered", turn_id, {"bytes": len(buffer)})

    async def vad_chunk(self, connection: ConnectionSession, turn_id: str, payload: dict[str, Any]) -> None:
        if turn_id in connection.unavailable_vad_turns:
            return
        encoded = payload.get("audio_base64") or payload.get("base64")
        if not isinstance(encoded, str):
            await connection.send("stt.error", turn_id, {"message": "audio_base64 is required"})
            return
        if int(payload.get("sample_rate", 0)) != 16_000 or payload.get("format", "pcm_s16le") != "pcm_s16le":
            await connection.send(
                "stt.error",
                turn_id,
                {"message": "Experimental VAD requires mono pcm_s16le at exactly 16000 Hz"},
            )
            return
        try:
            pcm = base64.b64decode(encoded, validate=True)
        except Exception:
            await connection.send("stt.error", turn_id, {"message": "Invalid base64 PCM audio"})
            return
        vad = connection.vad_sessions.setdefault(turn_id, SileroVADSession(self.settings.vad_threshold))
        try:
            events = await vad.feed_pcm16(pcm)
        except RuntimeError as exc:
            connection.unavailable_vad_turns.add(turn_id)
            connection.vad_sessions.pop(turn_id, None)
            await connection.send("stt.vad.unavailable", turn_id, {"message": str(exc), "fallback": "client_energy"})
            return
        for event in events:
            event_type = {
                "speech.started": "stt.speech.started",
                "speech.stopped": "stt.speech.stopped",
                "vad.confidence": "stt.vad.confidence",
            }[event.pop("type")]
            if event_type == "stt.speech.started":
                await self.cancel_active(connection, "voice_barge_in")
                await connection.send("turn.state", turn_id, {"state": "listening"})
            await connection.send(event_type, turn_id, event)

    async def audio_commit(self, connection: ConnectionSession, turn_id: str, payload: dict[str, Any]) -> None:
        audio = bytes(connection.audio_buffers.pop(turn_id, b""))
        vad = connection.vad_sessions.pop(turn_id, None)
        if vad:
            vad.reset()
        connection.unavailable_vad_turns.discard(turn_id)
        if not audio:
            await connection.send("stt.error", turn_id, {"message": "No buffered audio"})
            return
        await self.cancel_active(connection, "voice_barge_in")
        await connection.send("turn.state", turn_id, {"state": "transcribing"})
        try:
            result = await self.stt.transcribe_bytes(audio, suffix=str(payload.get("suffix", ".webm"))[:10])
        except Exception as exc:
            await connection.send("stt.error", turn_id, {"code": type(exc).__name__, "message": str(exc)[:500]})
            await connection.send("turn.state", turn_id, {"state": "idle"})
            return
        await connection.send("stt.final", turn_id, result.model_dump(mode="json"))
        if payload.get("submit") and result.text:
            next_payload = dict(payload)
            next_payload.update({"text": result.text, "source": "microphone"})
            await self.start_turn(connection, turn_id, next_payload)
        else:
            await connection.send("turn.state", turn_id, {"state": "idle"})
