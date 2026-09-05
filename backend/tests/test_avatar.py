from __future__ import annotations

import asyncio
import base64
import json
import struct
from datetime import UTC, datetime
from typing import Any

import pytest

from app.avatar.live2d import Live2DAvatarAdapter
from app.avatar.transport import AvatarEventFanout, Live2DStageServer
from app.core.config import Settings
from app.core.runtime import build_runtime


def source_event(event_type: str, payload: dict[str, Any], *, sequence: int = 4) -> dict[str, Any]:
    return {
        "type": event_type,
        "session_id": "session-avatar",
        "turn_id": "turn-avatar",
        "sequence": sequence,
        "timestamp": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "payload": payload,
    }


def test_live2d_adapter_maps_turn_states_with_canonical_envelope() -> None:
    command = Live2DAvatarAdapter().transform(source_event("turn.state", {"state": "transcribing"}))

    assert command is not None
    assert command["type"] == "avatar.state"
    assert command["session_id"] == "session-avatar"
    assert command["turn_id"] == "turn-avatar"
    assert command["sequence"] == 4
    assert command["timestamp"] == "2026-01-01T00:00:00Z"
    assert command["payload"]["state"] == "transcribing"
    assert command["payload"]["motion"] == "thinking"


def test_live2d_adapter_derives_pcm_lipsync_without_forwarding_audio() -> None:
    pcm = struct.pack("<4h", 0, 8192, -16384, 32767)
    command = Live2DAvatarAdapter().transform(
        source_event(
            "tts.audio",
            {
                "audio_base64": base64.b64encode(pcm).decode("ascii"),
                "output_format": "pcm_24000",
                "sample_rate": 24_000,
                "is_final": False,
            },
        )
    )

    assert command is not None
    assert command["type"] == "avatar.lipsync"
    assert 0 < command["payload"]["mouth_open"] <= 1
    assert command["payload"]["source"] == "pcm_amplitude"
    assert "audio_base64" not in command["payload"]
    assert "base64" not in command["payload"]


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"concern": 0.8, "excitement": 0.3}, "concerned"),
        ({"concern": 0.2, "excitement": 0.8}, "excited"),
        ({"concern": 0.2, "excitement": 0.4, "playfulness": 0.8}, "playful"),
        ({"warmth": 0.9}, "warm"),
    ],
)
def test_live2d_adapter_maps_bounded_emotions(values: dict[str, float], expected: str) -> None:
    command = Live2DAvatarAdapter().transform(source_event("emotion.state", {"values": values}))

    assert command is not None
    assert command["payload"]["expression"] == expected
    assert 0 <= command["payload"]["intensity"] <= 1


class CollectingSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def send_json(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)


async def test_avatar_fanout_preserves_primary_event_and_sanitizes_stage_event() -> None:
    primary = CollectingSink()
    stage = CollectingSink()
    fanout = AvatarEventFanout(primary, Live2DAvatarAdapter(), stage)
    event = source_event("text.delta", {"text": "private transcript"})

    await fanout.send_json(event)

    assert primary.events == [event]
    assert stage.events == []


def test_runtime_registers_optional_live2d_adapter() -> None:
    runtime = build_runtime(Settings(default_provider="mock"))

    adapter = runtime.avatar_registry.get("live2d")
    assert adapter.manifest.capabilities["pcm_amplitude_lipsync"] is True


async def test_stage_server_streams_only_valid_avatar_events_over_loopback() -> None:
    from websockets.asyncio.client import connect

    server = Live2DStageServer(port=0)
    await server.start()
    try:
        async with connect(server.url) as socket:
            command = Live2DAvatarAdapter().transform(source_event("turn.state", {"state": "thinking"}))
            assert command is not None
            await server.publish(command)
            received = json.loads(await asyncio.wait_for(socket.recv(), timeout=1))
            assert received["type"] == "avatar.state"
            assert received["payload"]["state"] == "thinking"
            with pytest.raises(ValueError, match="avatar commands only"):
                await server.publish(source_event("text.delta", {"text": "never publish this"}))
    finally:
        await server.close()
