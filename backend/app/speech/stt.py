from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings


class STTManifest(BaseModel):
    id: str
    display_name: str
    capabilities: dict[str, bool]
    settings_schema: dict[str, Any]
    required_secret_names: list[str] = Field(default_factory=list)


class SpeechSegment(BaseModel):
    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None


class TranscriptionResult(BaseModel):
    text: str
    language: str = "en"
    language_probability: float | None = None
    duration: float | None = None
    latency_ms: float
    model: str
    device: str
    compute_type: str
    segments: list[SpeechSegment]


class FasterWhisperSTT:
    provider_id = "faster-whisper"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None
        self._loaded_signature: tuple[str, str, str] | None = None
        self._load_lock = asyncio.Lock()
        self._cuda_dll_handles: list[Any] = []
        self._register_windows_cuda_dlls()
        self.manifest = STTManifest(
            id=self.provider_id,
            display_name="Faster-Whisper (local English)",
            capabilities={"streaming": False, "english_only": True, "cuda": True, "cpu_fallback": False},
            settings_schema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "default": settings.stt_model},
                    "device": {"type": "string", "enum": ["auto", "cuda", "cpu"], "default": settings.stt_device},
                    "compute_type": {"type": "string", "default": settings.stt_compute_type},
                },
            },
        )

    def _register_windows_cuda_dlls(self) -> None:
        """Make speech-extra CUDA 12 runtime DLLs visible to CTranslate2."""
        if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
            return
        package_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
        dll_directories: list[Path] = []
        for component in ("cublas", "cudnn", "cuda_nvrtc"):
            dll_directory = package_root / component / "bin"
            if dll_directory.is_dir():
                dll_directories.append(dll_directory)
                self._cuda_dll_handles.append(os.add_dll_directory(dll_directory))
        current_path = os.environ.get("PATH", "")
        existing = {entry.casefold() for entry in current_path.split(os.pathsep) if entry}
        additions = [str(path) for path in dll_directories if str(path).casefold() not in existing]
        if additions:
            os.environ["PATH"] = os.pathsep.join([*additions, current_path])

    @staticmethod
    def installed() -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    @staticmethod
    def cuda_available() -> bool:
        try:
            import ctranslate2

            return ctranslate2.get_cuda_device_count() > 0
        except Exception:
            return False

    def resolved_device(self) -> str:
        if self.settings.stt_device == "cuda":
            return "cuda"
        if self.settings.stt_device == "cpu":
            return "cpu"
        return "cuda" if self.cuda_available() else "cpu"

    def resolved_compute_type(self, device: str) -> str:
        if self.settings.stt_compute_type != "auto":
            return self.settings.stt_compute_type
        return "float16" if device == "cuda" else "int8"

    def status(self) -> dict[str, Any]:
        device = self.resolved_device()
        return {
            "provider_id": self.provider_id,
            "installed": self.installed(),
            "model": self.settings.stt_model,
            "configured_device": self.settings.stt_device,
            "device": device,
            "compute_type": self.resolved_compute_type(device),
            "cuda_available": self.cuda_available(),
            "language": "en",
            "loaded": self._model is not None,
        }

    async def _ensure_model(self, model_name: str | None = None) -> tuple[Any, str, str]:
        if not self.installed():
            raise RuntimeError("Faster-Whisper is optional; install with: pip install -e .[speech]")
        name = model_name or self.settings.stt_model
        device = self.resolved_device()
        compute_type = self.resolved_compute_type(device)
        signature = (name, device, compute_type)
        async with self._load_lock:
            if self._model is not None and self._loaded_signature == signature:
                return self._model, device, compute_type

            def load() -> Any:
                from faster_whisper import WhisperModel

                return WhisperModel(name, device=device, compute_type=compute_type)

            self._model = await asyncio.to_thread(load)
            self._loaded_signature = signature
        return self._model, device, compute_type

    async def transcribe_bytes(
        self,
        audio: bytes,
        suffix: str = ".webm",
        model_name: str | None = None,
        *,
        already_segmented: bool = False,
    ) -> TranscriptionResult:
        model, device, compute_type = await self._ensure_model(model_name)
        started = time.perf_counter()
        path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                handle.write(audio)
                path = handle.name

            def run() -> tuple[list[Any], Any]:
                segments_iter, info = model.transcribe(
                    path,
                    language="en",
                    beam_size=5,
                    vad_filter=not already_segmented,
                    condition_on_previous_text=False,
                )
                return list(segments_iter), info

            raw_segments, info = await asyncio.to_thread(run)
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        segments = [
            SpeechSegment(
                start=float(segment.start),
                end=float(segment.end),
                text=segment.text,
                avg_logprob=getattr(segment, "avg_logprob", None),
                no_speech_prob=getattr(segment, "no_speech_prob", None),
            )
            for segment in raw_segments
        ]
        return TranscriptionResult(
            text="".join(segment.text for segment in segments).strip(),
            language="en",
            language_probability=getattr(info, "language_probability", None),
            duration=getattr(info, "duration", None),
            latency_ms=(time.perf_counter() - started) * 1000,
            model=model_name or self.settings.stt_model,
            device=device,
            compute_type=compute_type,
            segments=segments,
        )


class SileroEndpointDetector:
    """Streaming speech start/end detector for 16 kHz mono PCM frames."""

    frame_samples = 512
    frame_bytes = frame_samples * 2

    def __init__(self, threshold: float = 0.5, silence_ms: int = 900) -> None:
        self.threshold = threshold
        self.silence_ms = silence_ms
        self._iterator: Any | None = None

    def _load(self) -> Any:
        if self._iterator is None:
            from silero_vad import VADIterator, load_silero_vad

            self._iterator = VADIterator(
                load_silero_vad(),
                threshold=self.threshold,
                sampling_rate=16_000,
                min_silence_duration_ms=self.silence_ms,
                speech_pad_ms=96,
            )
        return self._iterator

    def feed_pcm16(self, frame: bytes) -> dict[str, int] | None:
        if len(frame) != self.frame_bytes:
            raise ValueError(f"Silero requires exactly {self.frame_bytes} bytes per 16 kHz frame")
        import numpy as np
        import torch

        samples = np.frombuffer(frame, dtype=np.int16).astype("float32") / 32768.0
        with torch.inference_mode():
            event = self._load()(torch.from_numpy(samples), return_seconds=False)
        if not event:
            return None
        return {str(key): int(value) for key, value in event.items()}

    def reset(self) -> None:
        if self._iterator is not None:
            self._iterator.reset_states()


class SileroVADSession:
    """Optional stateful 16 kHz Silero VAD, consuming exact 512-sample frames."""

    frame_bytes = 512 * 2

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self._buffer = bytearray()
        self._model: Any | None = None
        self.speaking = False
        self.frame_index = 0

    def _load(self) -> Any:
        if self._model is None:
            try:
                from silero_vad import load_silero_vad
            except ImportError as exc:
                raise RuntimeError("Silero VAD is optional; install with: pip install -e .[speech]") from exc
            self._model = load_silero_vad()
            reset = getattr(self._model, "reset_states", None)
            if reset:
                reset()
        return self._model

    async def feed_pcm16(self, chunk: bytes) -> list[dict[str, Any]]:
        self._buffer.extend(chunk)
        events: list[dict[str, Any]] = []
        while len(self._buffer) >= self.frame_bytes:
            frame = bytes(self._buffer[: self.frame_bytes])
            del self._buffer[: self.frame_bytes]

            def infer(frame_data: bytes = frame) -> float:
                import numpy as np
                import torch

                samples = np.frombuffer(frame_data, dtype=np.int16).astype("float32") / 32768.0
                tensor = torch.from_numpy(samples)
                return float(self._load()(tensor, 16_000).item())

            confidence = await asyncio.to_thread(infer)
            timestamp = self.frame_index * 512 / 16_000
            self.frame_index += 1
            if confidence >= self.threshold and not self.speaking:
                self.speaking = True
                events.append({"type": "speech.started", "time": timestamp, "confidence": confidence})
            elif confidence < max(0.15, self.threshold * 0.6) and self.speaking:
                self.speaking = False
                events.append({"type": "speech.stopped", "time": timestamp, "confidence": confidence})
            else:
                events.append({"type": "vad.confidence", "time": timestamp, "confidence": confidence})
        return events

    def reset(self) -> None:
        self._buffer.clear()
        self.speaking = False
        self.frame_index = 0
        if self._model is not None and hasattr(self._model, "reset_states"):
            self._model.reset_states()
