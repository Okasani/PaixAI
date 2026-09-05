from __future__ import annotations

import asyncio
import io
import threading
import wave
from collections import deque
from typing import Any

from app.speech.stt import SileroEndpointDetector


class AudioDependencyError(RuntimeError):
    pass


def _sounddevice() -> Any:
    try:
        import sounddevice
    except ImportError as exc:
        raise AudioDependencyError(
            "Voice I/O is not installed. Run scripts/setup.ps1 or install the backend speech extra."
        ) from exc
    return sounddevice


def pcm16_to_wav(pcm: bytes, *, sample_rate: int = 16_000, channels: int = 1) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()


def list_audio_devices() -> str:
    return str(_sounddevice().query_devices())


def record_push_to_talk(*, device: str | int | None = None, sample_rate: int = 16_000) -> bytes:
    sounddevice = _sounddevice()
    chunks: list[bytes] = []

    def capture(indata: Any, _frames: int, _time: Any, _status: Any) -> None:
        chunks.append(bytes(indata))

    with sounddevice.RawInputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
        device=device,
        callback=capture,
    ):
        input("Recording... speak now, then press Enter to stop. ")
    return pcm16_to_wav(b"".join(chunks), sample_rate=sample_rate)


class _UtteranceBuffer:
    def __init__(self, *, pre_roll_frames: int, max_frames: int) -> None:
        self._pre_roll: deque[bytes] = deque(maxlen=pre_roll_frames)
        self._frames: list[bytes] = []
        self.max_frames = max_frames
        self.started = False

    def feed(self, frame: bytes, event: dict[str, int] | None) -> str | None:
        if not self.started:
            self._pre_roll.append(frame)
            if event and "start" in event:
                self.started = True
                self._frames.extend(self._pre_roll)
                self._pre_roll.clear()
                return "started"
            return None
        self._frames.append(frame)
        if (event and "end" in event) or len(self._frames) >= self.max_frames:
            return "ended"
        return None

    @property
    def pcm(self) -> bytes:
        return b"".join(self._frames)


async def record_until_silence(
    *,
    device: str | int | None = None,
    sample_rate: int = 16_000,
    vad_threshold: float = 0.5,
    silence_ms: int = 900,
    max_seconds: float = 30.0,
) -> bytes:
    if sample_rate != 16_000:
        raise ValueError("Silero hands-free capture requires a 16 kHz sample rate")
    sounddevice = _sounddevice()
    detector = SileroEndpointDetector(vad_threshold, silence_ms)
    frames: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
    loop = asyncio.get_running_loop()

    def enqueue(frame: bytes) -> None:
        if frames.full():
            try:
                frames.get_nowait()
            except asyncio.QueueEmpty:
                pass
        frames.put_nowait(frame)

    def capture(indata: Any, _frame_count: int, _time: Any, _status: Any) -> None:
        try:
            loop.call_soon_threadsafe(enqueue, bytes(indata))
        except RuntimeError:
            pass

    capture_buffer = _UtteranceBuffer(
        pre_roll_frames=max(1, round(0.4 * sample_rate / detector.frame_samples)),
        max_frames=max(1, round(max_seconds * sample_rate / detector.frame_samples)),
    )
    print("Listening continuously... speak naturally; a short pause submits your sentence.", flush=True)
    detector.reset()
    try:
        with sounddevice.RawInputStream(
            samplerate=sample_rate,
            blocksize=detector.frame_samples,
            channels=1,
            dtype="int16",
            device=device,
            callback=capture,
        ):
            while True:
                frame = await frames.get()
                if len(frame) != detector.frame_bytes:
                    continue
                state = detector.feed_pcm16(frame)
                capture_state = capture_buffer.feed(frame, state)
                if capture_state == "started":
                    print("[speech detected]", flush=True)
                elif capture_state == "ended":
                    break
    finally:
        detector.reset()
    return pcm16_to_wav(capture_buffer.pcm, sample_rate=sample_rate)


class PCMPlayer:
    def __init__(self, device: str | int | None = None) -> None:
        self.device = device
        self._stream: Any | None = None
        self._sample_rate: int | None = None
        self._lock = threading.Lock()

    def write(self, audio: bytes, sample_rate: int) -> None:
        if not audio:
            return
        usable = audio[: len(audio) - (len(audio) % 2)]
        if not usable:
            return
        with self._lock:
            if self._stream is None or self._sample_rate != sample_rate:
                self._close_locked()
                sounddevice = _sounddevice()
                self._stream = sounddevice.RawOutputStream(
                    samplerate=sample_rate,
                    channels=1,
                    dtype="int16",
                    device=self.device,
                )
                self._stream.start()
                self._sample_rate = sample_rate
            self._stream.write(usable)

    def cancel(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.abort()
                self._close_locked()

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        if self._stream is not None:
            self._stream.close()
        self._stream = None
        self._sample_rate = None
