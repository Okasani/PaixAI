from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.security import secret_store
from app.providers.llm.base import CancellationToken, HealthResult


class VoiceInfo(BaseModel):
    voice_id: str
    name: str
    category: str | None = None
    description: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    preview_url: str | None = None


class AudioChunk(BaseModel):
    audio_base64: str
    output_format: str
    sample_rate: int
    is_final: bool = False
    alignment: dict[str, Any] | None = None


class TTSManifest(BaseModel):
    id: str
    display_name: str
    capabilities: dict[str, bool]
    settings_schema: dict[str, Any]
    required_secret_names: list[str]


class ElevenLabsTTS:
    provider_id = "elevenlabs"
    api_base = "https://api.elevenlabs.io"
    ws_base = "wss://api.elevenlabs.io"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.manifest = TTSManifest(
            id=self.provider_id,
            display_name="ElevenLabs realtime TTS",
            capabilities={"streaming": True, "voice_discovery": True, "pcm": True},
            required_secret_names=["ELEVENLABS_API_KEY"],
            settings_schema={
                "type": "object",
                "properties": {
                    "voice_id": {"type": "string", "default": settings.elevenlabs_voice_id or ""},
                    "model_id": {"type": "string", "default": settings.elevenlabs_model_id},
                    "output_format": {"type": "string", "default": settings.elevenlabs_output_format},
                    "stability": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                    "similarity_boost": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.75},
                    "style": {"type": "number", "minimum": 0, "maximum": 1, "default": 0},
                    "use_speaker_boost": {"type": "boolean", "default": True},
                },
            },
        )

    def _file_key(self) -> str | None:
        path = self.settings.elevenlabs_api_key_file
        if path is None:
            return None
        try:
            resolved = Path(path).resolve(strict=True)
            if not resolved.is_file() or resolved.stat().st_size > 16_384:
                return None
            value = resolved.read_text(encoding="utf-8").removeprefix("\ufeff").strip()
            return value or None
        except (OSError, UnicodeError):
            return None

    def _key(self) -> str | None:
        env_value = self.settings.elevenlabs_api_key.get_secret_value() if self.settings.elevenlabs_api_key else None
        return secret_store.get("ELEVENLABS_API_KEY", env_value) or self._file_key()

    def configured(self) -> bool:
        return bool(self._key())

    def _headers(self) -> dict[str, str]:
        key = self._key()
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY is not configured")
        return {"xi-api-key": key}

    @staticmethod
    def sample_rate_for(output_format: str) -> int:
        match = output_format.rsplit("_", 1)
        if len(match) == 2 and match[1].isdigit():
            return int(match[1])
        return 44_100

    async def health_check(self) -> HealthResult:
        if not self.configured():
            return HealthResult(status="unavailable", message="ELEVENLABS_API_KEY is not configured")
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.api_base}/v2/voices", headers=self._headers(), params={"page_size": 1}
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                message = (
                    f"ElevenLabs rejected the voice-list request (HTTP {status}). "
                    "Replace the key or grant it voice-read permission."
                )
            else:
                message = f"ElevenLabs health request failed (HTTP {status})"
            return HealthResult(status="unavailable", message=message)
        except Exception as exc:
            return HealthResult(status="unavailable", message=f"ElevenLabs connection failed: {type(exc).__name__}")
        return HealthResult(
            status="ok", message="ElevenLabs is reachable", latency_ms=(time.perf_counter() - started) * 1000
        )

    async def list_voices(self) -> list[VoiceInfo]:
        if not self.configured():
            return []
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.api_base}/v2/voices", headers=self._headers(), params={"page_size": 100}
            )
            response.raise_for_status()
        return [
            VoiceInfo(
                voice_id=item["voice_id"],
                name=item.get("name", item["voice_id"]),
                category=item.get("category"),
                description=item.get("description"),
                labels=item.get("labels") or {},
                preview_url=item.get("preview_url"),
            )
            for item in response.json().get("voices", [])
            if item.get("voice_id")
        ]

    async def list_models(self) -> list[dict[str, Any]]:
        if not self.configured():
            return [{"model_id": self.settings.elevenlabs_model_id, "name": "Eleven Flash v2.5"}]
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{self.api_base}/v1/models", headers=self._headers())
            response.raise_for_status()
        return [model for model in response.json() if model.get("can_do_text_to_speech", True)]

    async def generate_sample(
        self,
        *,
        text: str,
        voice_id: str,
        model_id: str | None = None,
        output_format: str = "mp3_44100_128",
        voice_settings: dict[str, Any] | None = None,
    ) -> tuple[bytes, dict[str, float | str]]:
        if not self.configured():
            raise RuntimeError("ELEVENLABS_API_KEY is not configured")
        started = time.perf_counter()
        url = f"{self.api_base}/v1/text-to-speech/{voice_id}/stream"
        body = {
            "text": text,
            "model_id": model_id or self.settings.elevenlabs_model_id,
            "voice_settings": voice_settings or {"stability": 0.5, "similarity_boost": 0.75},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url, headers=self._headers(), params={"output_format": output_format}, json=body
            )
            response.raise_for_status()
            audio = response.content
        elapsed = (time.perf_counter() - started) * 1000
        return audio, {
            "time_to_first_audio_ms": elapsed,
            "total_generation_ms": elapsed,
            "output_format": output_format,
        }

    async def stream_audio(
        self,
        text_chunks: AsyncIterator[str],
        cancellation: CancellationToken,
        *,
        voice_id: str,
        model_id: str | None = None,
        output_format: str | None = None,
        voice_settings: dict[str, Any] | None = None,
    ) -> AsyncIterator[AudioChunk]:
        if not self.configured():
            raise RuntimeError("ELEVENLABS_API_KEY is not configured")
        try:
            from websockets.asyncio.client import connect
        except ImportError:
            try:
                from websockets import connect
            except ImportError as exc:
                raise RuntimeError("Install the 'websockets' backend dependency") from exc
        selected_model = model_id or self.settings.elevenlabs_model_id
        selected_format = output_format or self.settings.elevenlabs_output_format
        url = (
            f"{self.ws_base}/v1/text-to-speech/{voice_id}/stream-input"
            f"?model_id={selected_model}&output_format={selected_format}"
        )
        sample_rate = self.sample_rate_for(selected_format)
        socket = await connect(url, max_size=4 * 1024 * 1024, ping_interval=20, ping_timeout=20)
        sender_error: BaseException | None = None

        async def send_text() -> None:
            nonlocal sender_error
            try:
                selected_voice_settings = voice_settings or {}
                schedule = selected_voice_settings.get("chunk_length_schedule", [50, 90, 120, 150])
                clean_voice_settings = {
                    key: value
                    for key, value in selected_voice_settings.items()
                    if key in {"stability", "similarity_boost", "style", "use_speaker_boost", "speed"}
                } or {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True}
                await socket.send(
                    json.dumps(
                        {
                            "text": " ",
                            "xi_api_key": self._key(),
                            "voice_settings": clean_voice_settings,
                            "generation_config": {"chunk_length_schedule": schedule},
                        }
                    )
                )
                sent_content = False
                async for text in text_chunks:
                    if cancellation.cancelled:
                        break
                    if text:
                        await socket.send(
                            json.dumps(
                                {
                                    "text": text if text[-1].isspace() else text + " ",
                                    "try_trigger_generation": True,
                                }
                            )
                        )
                        sent_content = True
                if not cancellation.cancelled:
                    # Content is forwarded immediately for low latency. A final
                    # whitespace frame flushes the buffered content, followed by
                    # the separately documented empty-text EOS frame.
                    await socket.send(
                        json.dumps(
                            {
                                "text": " ",
                                "flush": True,
                                "try_trigger_generation": sent_content,
                            }
                        )
                    )
                    # ElevenLabs documents a separate empty-text message as EOS.
                    await socket.send(json.dumps({"text": ""}))
            except BaseException as exc:  # surfaced to receiver loop
                sender_error = exc

        sender = asyncio.create_task(send_text())
        try:
            while not cancellation.cancelled:
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=0.25)
                except TimeoutError:
                    if sender.done() and sender_error:
                        raise sender_error from None
                    continue
                if isinstance(raw, bytes):
                    yield AudioChunk(
                        audio_base64=base64.b64encode(raw).decode("ascii"),
                        output_format=selected_format,
                        sample_rate=sample_rate,
                    )
                    continue
                data = json.loads(raw)
                audio = data.get("audio")
                if audio:
                    yield AudioChunk(
                        audio_base64=audio,
                        output_format=selected_format,
                        sample_rate=sample_rate,
                        alignment=data.get("normalizedAlignment") or data.get("alignment"),
                    )
                if data.get("isFinal") or data.get("is_final"):
                    yield AudioChunk(
                        audio_base64="", output_format=selected_format, sample_rate=sample_rate, is_final=True
                    )
                    break
        finally:
            cancellation.cancel() if sender_error else None
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            await socket.close()
