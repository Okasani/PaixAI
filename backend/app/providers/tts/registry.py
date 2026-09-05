from __future__ import annotations

import base64

from app.core.config import Settings
from app.providers.llm.base import HealthResult
from app.providers.registry import ComponentRegistry
from app.providers.tts.local import LocalTTS
from app.speech.tts import AudioChunk, ElevenLabsTTS


class MockTTS(LocalTTS):
    provider_id = "mock"

    def configured(self) -> bool:
        return True

    async def health_check(self) -> HealthResult:
        return HealthResult(status="ok", message="Mock TTS ready")

    async def stream_audio(self, text_chunks, cancellation, **kwargs):
        async for _ in text_chunks:
            if cancellation.cancelled:
                return
            yield AudioChunk(
                audio_base64=base64.b64encode(b"\x00\x00" * 2400).decode(), output_format="pcm_24000", sample_rate=24000
            )
        if not cancellation.cancelled:
            yield AudioChunk(audio_base64="", output_format="pcm_24000", sample_rate=24000, is_final=True)


def build_tts_registry(settings: Settings) -> ComponentRegistry:
    registry = ComponentRegistry()
    for adapter in (LocalTTS(settings), ElevenLabsTTS(settings), MockTTS(settings)):
        registry.register(adapter)
    return registry
