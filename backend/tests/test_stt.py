from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.speech.stt import FasterWhisperSTT


@pytest.mark.asyncio
async def test_cuda_model_load_failure_does_not_fall_back_to_cpu(monkeypatch) -> None:
    monkeypatch.setenv("PAIX_STT_DEVICE", "cuda")
    monkeypatch.setenv("PAIX_STT_COMPUTE_TYPE", "float16")
    settings = Settings(_env_file=None)
    stt = FasterWhisperSTT(settings)
    monkeypatch.setattr(stt, "installed", lambda: True)
    attempts: list[tuple[str, str]] = []

    def fail_to_load(_name: str, *, device: str, compute_type: str) -> None:
        attempts.append((device, compute_type))
        raise RuntimeError("CUDA runtime unavailable")

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=fail_to_load))

    with pytest.raises(RuntimeError, match="CUDA runtime unavailable"):
        await stt._ensure_model()

    assert attempts == [("cuda", "float16")]
