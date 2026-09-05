from __future__ import annotations

import base64
import math
import sys
from array import array
from typing import Any

from pydantic import BaseModel, Field

from app.events.schemas import RealtimeEvent


class AvatarManifest(BaseModel):
    id: str
    display_name: str
    capabilities: dict[str, bool]
    supported_states: list[str] = Field(default_factory=list)


class Live2DAvatarAdapter:
    """Translate Paix events into renderer-neutral Live2D commands.

    The stage only receives these derived commands. User text, transcripts, tool
    results, hidden reasoning, and raw PCM are deliberately excluded.
    """

    provider_id = "live2d"

    _state_motion = {
        "idle": "idle",
        "listening": "listening",
        "transcribing": "thinking",
        "thinking": "thinking",
        "speaking": "speaking",
        "interrupted": "interrupted",
        "error": "error",
    }

    def __init__(self) -> None:
        self.manifest = AvatarManifest(
            id=self.provider_id,
            display_name="Live2D Cubism stage",
            capabilities={
                "state_animation": True,
                "expressions": True,
                "motions": True,
                "pcm_amplitude_lipsync": True,
                "phoneme_lipsync": False,
                "idle_motion": True,
            },
            supported_states=list(self._state_motion),
        )

    def transform(self, raw_event: dict[str, Any]) -> dict[str, Any] | None:
        event = RealtimeEvent.model_validate(raw_event)
        payload: dict[str, Any]
        command_type: str

        if event.type == "session.ready":
            command_type = "avatar.state"
            payload = self._state_payload("idle")
        elif event.type == "turn.state":
            state = str(event.payload.get("state", ""))
            if state not in self._state_motion:
                return None
            command_type = "avatar.state"
            payload = self._state_payload(state)
        elif event.type == "response.cancelled":
            command_type = "avatar.state"
            payload = {**self._state_payload("interrupted"), "hold_ms": 450}
        elif event.type in {"provider.error", "stt.error", "tts.error", "websocket.error"}:
            command_type = "avatar.state"
            payload = self._state_payload("error")
        elif event.type == "emotion.state":
            command_type = "avatar.expression"
            payload = self._expression_payload(event.payload)
        elif event.type == "tts.audio":
            command_type = "avatar.lipsync"
            payload = self._lipsync_payload(event.payload)
        else:
            return None

        return RealtimeEvent(
            type=command_type,
            session_id=event.session_id,
            turn_id=event.turn_id,
            sequence=event.sequence,
            timestamp=event.timestamp,
            payload=payload,
        ).wire()

    def _state_payload(self, state: str) -> dict[str, Any]:
        return {
            "state": state,
            "motion": self._state_motion[state],
            "transition_ms": 180 if state in {"speaking", "interrupted"} else 260,
        }

    @staticmethod
    def _expression_payload(payload: dict[str, Any]) -> dict[str, Any]:
        raw_values = payload.get("values")
        values = raw_values if isinstance(raw_values, dict) else {}

        def bounded(name: str, default: float) -> float:
            value = values.get(name, default)
            try:
                return min(1.0, max(0.0, float(value)))
            except (TypeError, ValueError):
                return default

        concern = bounded("concern", 0.2)
        excitement = bounded("excitement", 0.42)
        playfulness = bounded("playfulness", 0.48)
        warmth = bounded("warmth", 0.78)
        confidence = bounded("confidence", 0.72)

        if concern >= 0.55 and concern >= excitement:
            expression, intensity = "concerned", concern
        elif excitement >= 0.62:
            expression, intensity = "excited", excitement
        elif playfulness >= 0.68:
            expression, intensity = "playful", playfulness
        elif confidence <= 0.35:
            expression, intensity = "shy", 1.0 - confidence
        elif warmth >= 0.72:
            expression, intensity = "warm", warmth
        else:
            expression, intensity = "neutral", 0.5
        return {"expression": expression, "intensity": round(intensity, 4)}

    @classmethod
    def _lipsync_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        encoded = payload.get("audio_base64") or payload.get("base64")
        is_final = bool(payload.get("is_final", False))
        output_format = str(payload.get("output_format", ""))
        sample_rate = cls._positive_int(payload.get("sample_rate"), 24_000)
        if is_final or not isinstance(encoded, str) or not encoded:
            return {"mouth_open": 0.0, "duration_ms": 0.0, "source": "pcm_amplitude"}
        if not output_format.startswith("pcm"):
            return {"mouth_open": 0.55, "duration_ms": 80.0, "source": "speech_activity"}
        try:
            pcm = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            return {"mouth_open": 0.0, "duration_ms": 0.0, "source": "pcm_amplitude"}
        usable = pcm[: len(pcm) - (len(pcm) % 2)]
        if not usable:
            return {"mouth_open": 0.0, "duration_ms": 0.0, "source": "pcm_amplitude"}
        samples = array("h")
        samples.frombytes(usable)
        if sys.byteorder != "little":
            samples.byteswap()
        stride = max(1, len(samples) // 4096)
        selected = samples[::stride]
        rms = math.sqrt(sum((sample / 32768.0) ** 2 for sample in selected) / len(selected))
        return {
            "mouth_open": round(min(1.0, rms * 4.5), 4),
            "duration_ms": round(len(samples) * 1000 / sample_rate, 2),
            "source": "pcm_amplitude",
        }

    @staticmethod
    def _positive_int(value: object, default: int) -> int:
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default
