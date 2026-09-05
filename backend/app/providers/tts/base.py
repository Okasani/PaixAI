from collections.abc import AsyncIterator
from typing import Any, Protocol

from app.providers.llm.base import CancellationToken, HealthResult
from app.speech.tts import AudioChunk, TTSManifest, VoiceInfo


class TTSProvider(Protocol):
    provider_id: str
    manifest: TTSManifest

    def configured(self) -> bool: ...
    async def health_check(self) -> HealthResult: ...
    async def list_voices(self) -> list[VoiceInfo]: ...
    async def list_models(self) -> list[dict[str, Any]]: ...
    def stream_audio(
        self,
        text_chunks: AsyncIterator[str],
        cancellation: CancellationToken,
        *,
        voice_id: str,
        model_id: str | None = None,
        output_format: str | None = None,
        voice_settings: dict[str, Any] | None = None,
    ) -> AsyncIterator[AudioChunk]: ...
