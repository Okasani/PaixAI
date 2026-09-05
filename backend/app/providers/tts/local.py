"""Local Style-Bert-VITS2 bridge; only JSON bodies, never text in request URLs."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import Settings
from app.providers.llm.base import CancellationToken, HealthResult
from app.speech.tts import AudioChunk, TTSManifest, VoiceInfo


class LocalTTS:
    provider_id = "style_bert_vits2"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport
        self.manifest = TTSManifest(
            id=self.provider_id,
            display_name="Local Style-Bert-VITS2",
            capabilities={"streaming": True, "phrase_streaming": True, "pcm": True, "voice_discovery": True},
            settings_schema={},
            required_secret_names=[],
        )

    def configured(self) -> bool:
        return self.settings.local_tts_assets_approved

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.settings.local_tts_base_url,
            transport=self.transport,
            timeout=120,
            trust_env=False,
            follow_redirects=False,
        )

    async def health_check(self) -> HealthResult:
        if not self.configured():
            return HealthResult(
                status="unavailable", message="Configure licensed local voice assets in config/voice.json"
            )
        try:
            async with self.client() as client:
                response = await client.get("/health", timeout=3)
                response.raise_for_status()
                if response.json().get("ready") is not True:
                    raise ValueError("not ready")
            return HealthResult(status="ok", message="Local TTS bridge ready")
        except (httpx.HTTPError, ValueError):
            return HealthResult(status="unavailable", message="Local TTS bridge unavailable; no cloud fallback")

    async def list_voices(self) -> list[VoiceInfo]:
        return (
            [VoiceInfo(voice_id=self.settings.local_tts_voice_id, name="Configured local voice")]
            if self.configured()
            else []
        )

    async def list_models(self) -> list[dict[str, Any]]:
        return [{"model_id": str(self.settings.local_tts_model_id), "name": "Configured local Style-Bert-VITS2 model"}]

    async def _synthesize(self, client: httpx.AsyncClient, body: dict) -> tuple[int, bytes]:
        async with client.stream("POST", "/synthesize", json=body) as response:
            if response.status_code != 200:
                raise RuntimeError("Local TTS synthesis failed; check bridge health")
            try:
                rate = int(response.headers.get("x-sample-rate", "0"))
            except ValueError:
                raise RuntimeError("Local TTS returned invalid PCM metadata") from None
            if rate not in {16000, 22050, 24000, 32000, 44100, 48000}:
                raise RuntimeError("Local TTS returned invalid PCM metadata")
            pcm = bytearray()
            async for block in response.aiter_bytes():
                if len(pcm) + len(block) > 16_000_000:
                    raise RuntimeError("Local TTS exceeded the audio limit")
                pcm.extend(block)
            if not pcm or len(pcm) % 2:
                raise RuntimeError("Local TTS returned invalid PCM")
            return rate, bytes(pcm)

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
            raise RuntimeError("Local voice assets are not configured and approved")
        async with self.client() as client:
            async for text in text_chunks:
                if cancellation.cancelled:
                    return
                task = asyncio.create_task(
                    self._synthesize(
                        client,
                        {
                            "text": text,
                            "speaker_id": int(voice_id),
                            "model_id": int(model_id or self.settings.local_tts_model_id),
                            "language": self.settings.local_tts_language,
                            "style": self.settings.local_tts_style,
                        },
                    )
                )
                try:
                    while not task.done():
                        await asyncio.wait({task}, timeout=0.05)
                        if cancellation.cancelled:
                            return
                    rate, pcm = task.result()
                    size = rate // 10 * 2  # 100 ms playback chunks, mono signed 16-bit little-endian.
                    for offset in range(0, len(pcm), size):
                        if cancellation.cancelled:
                            return
                        yield AudioChunk(
                            audio_base64=base64.b64encode(pcm[offset : offset + size]).decode(),
                            sample_rate=rate,
                            output_format=f"pcm_{rate}",
                        )
                        try:
                            await asyncio.wait_for(cancellation.wait(), len(pcm[offset : offset + size]) / (rate * 2))
                            return
                        except TimeoutError:
                            pass
                except httpx.HTTPError:
                    raise RuntimeError("Local TTS bridge unavailable; no cloud fallback") from None
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        if not cancellation.cancelled:
            yield AudioChunk(audio_base64="", sample_rate=24000, output_format="pcm_24000", is_final=True)

    async def generate_sample(
        self,
        *,
        text: str,
        voice_id: str,
        model_id: str | None = None,
        output_format: str = "pcm_24000",
        voice_settings: dict | None = None,
    ):
        async def phrases():
            yield text

        data = bytearray()
        rate = 24000
        async for chunk in self.stream_audio(phrases(), CancellationToken(), voice_id=voice_id, model_id=model_id):
            if chunk.audio_base64:
                data.extend(base64.b64decode(chunk.audio_base64))
                rate = chunk.sample_rate
        return bytes(data), {"output_format": f"pcm_{rate}", "sample_rate": rate}
