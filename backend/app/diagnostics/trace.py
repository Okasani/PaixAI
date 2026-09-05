from __future__ import annotations

import json
import re
from pathlib import Path

from app.events.schemas import RealtimeEvent

SAFE_TYPES = frozenset(
    {
        "session.ready",
        "turn.state",
        "response.started",
        "response.completed",
        "response.cancelled",
        "audio.cancelled",
        "audio.buffered",
        "stt.final",
        "stt.error",
        "stt.speech.started",
        "stt.speech.stopped",
        "prompt.compiled",
        "text.delta",
        "tts.phrase",
        "tts.audio",
        "tts.error",
        "tts.skipped",
        "provider.error",
        "pipeline.metric",
        "emotion.state",
        "avatar.state",
        "avatar.expression",
        "avatar.lipsync",
    }
)
SAFE_STATES = {"idle", "listening", "transcribing", "thinking", "speaking", "interrupted", "error"}
SAFE_METRICS = {"context_assembly", "time_to_first_audio", "time_to_first_llm_token", "total_turn_latency"}


def safe_record(raw: dict) -> dict:
    event = RealtimeEvent.model_validate(raw)
    # Stable pseudonyms preserve correlation without exposing user-supplied identifiers.
    import hashlib

    def identifier(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:20]

    payload = {}
    if isinstance(event.payload.get("state"), str) and event.payload["state"] in SAFE_STATES:
        payload["state"] = event.payload["state"]
    if isinstance(event.payload.get("name"), str) and event.payload["name"] in SAFE_METRICS:
        payload["name"] = event.payload["name"]
        duration = event.payload.get("duration_ms")
        if isinstance(duration, int | float) and 0 <= duration <= 86_400_000:
            payload["duration_ms"] = duration
    return {
        "session_id": identifier(event.session_id),
        "turn_id": identifier(event.turn_id),
        "sequence": event.sequence,
        "timestamp": event.timestamp.isoformat().replace("+00:00", "Z"),
        "type": event.type if event.type in SAFE_TYPES else "other",
        "payload": payload,
    }


class TraceWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.failed = False

    def write(self, event: dict) -> None:
        try:
            record = safe_record(event)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > 5 * 1024 * 1024:
                self.path.replace(self.path.with_suffix(".previous.jsonl"))
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, allow_nan=False) + "\n")
        except (OSError, ValueError):
            self.failed = True  # Diagnostics must not break a spoken turn.


def export_traces(source: Path, destination: Path) -> int:
    # Revalidate even a locally tampered trace before exporting it.
    records = []
    if source.exists():
        if source.stat().st_size > 6 * 1024 * 1024:
            raise ValueError("Trace file exceeds export limit")
        for line in source.read_text(encoding="utf-8").splitlines():
            original = json.loads(line)
            record = safe_record(original)
            for key in ("session_id", "turn_id"):
                if isinstance(original.get(key), str) and re.fullmatch(r"[a-f0-9]{20}", original[key]):
                    record[key] = original[key]
            records.append(record)
    with destination.open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, allow_nan=False) + "\n")
    return len(records)
