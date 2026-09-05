from __future__ import annotations

import io
import wave

import pytest

from app.voice.audio import _UtteranceBuffer, pcm16_to_wav, record_until_silence
from app.voice.cli import QueueEventSink, TerminalEvents, _device, build_parser


def test_pcm16_to_wav_builds_mono_16khz_audio() -> None:
    pcm = b"\x01\x00\xff\x7f" * 100
    encoded = pcm16_to_wav(pcm)

    with wave.open(io.BytesIO(encoded), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16_000
        assert wav.readframes(wav.getnframes()) == pcm


def test_voice_cli_defaults_to_persistent_voice_conversation() -> None:
    args = build_parser().parse_args([])

    assert args.conversation_id == "voice-primary"
    assert args.typed_only is False
    assert args.push_to_talk is False
    assert _device("4") == 4
    assert _device("Microphone Array") == "Microphone Array"


@pytest.mark.asyncio
async def test_empty_transcript_is_reported_as_no_speech(capsys) -> None:
    terminal = TerminalEvents(QueueEventSink(), None)

    await terminal.handle({"type": "stt.final", "turn_id": "turn-1", "payload": {"text": ""}})

    assert capsys.readouterr().out == "[no speech detected]\n"


def test_utterance_buffer_keeps_pre_roll_and_stops_on_silero_end() -> None:
    capture = _UtteranceBuffer(pre_roll_frames=2, max_frames=10)

    assert capture.feed(b"a", None) is None
    assert capture.feed(b"b", {"start": 512}) == "started"
    assert capture.feed(b"c", None) is None
    assert capture.feed(b"d", {"end": 2_048}) == "ended"

    assert capture.pcm == b"abcd"


@pytest.mark.asyncio
async def test_hands_free_capture_stops_after_detected_pause(monkeypatch) -> None:
    frame = b"\x01\x00" * 512

    class FakeDetector:
        frame_samples = 512
        frame_bytes = 1_024

        def __init__(self, _threshold: float, _silence_ms: int) -> None:
            self.events = iter(({"start": 0}, None, {"end": 1_536}))

        def feed_pcm16(self, _frame: bytes) -> dict[str, int] | None:
            return next(self.events)

        def reset(self) -> None:
            pass

    class FakeStream:
        def __init__(self, callback, **_kwargs) -> None:
            self.callback = callback

        def __enter__(self):
            for _ in range(3):
                self.callback(frame, 512, None, None)
            return self

        def __exit__(self, *_args) -> None:
            pass

    class FakeSoundDevice:
        RawInputStream = FakeStream

    monkeypatch.setattr("app.voice.audio.SileroEndpointDetector", FakeDetector)
    monkeypatch.setattr("app.voice.audio._sounddevice", lambda: FakeSoundDevice())

    encoded = await record_until_silence(max_seconds=5)

    with wave.open(io.BytesIO(encoded), "rb") as wav:
        assert wav.readframes(wav.getnframes()) == frame * 3
