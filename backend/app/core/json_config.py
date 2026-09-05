"""Owner-editable configuration. Validation errors never echo input values."""

from __future__ import annotations

import json
import os
import tempfile
from ipaddress import ip_address
from pathlib import Path
from typing import Literal, TypeVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ConfigFileError(ValueError):
    """An input-free, user-facing file and JSON-path error."""


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def loopback_url(value: str) -> str:
    parsed = urlsplit(value)
    try:
        valid = parsed.hostname == "localhost" or ip_address(parsed.hostname or "").is_loopback
        port = parsed.port
    except ValueError:
        valid = False
        port = None
    if not valid or parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Expected a plain loopback HTTP URL")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid port")
    return value.rstrip("/")


class RuntimeProfile(StrictConfig):
    schema_version: Literal[1] = 1
    default_provider: Literal["local", "mock", "openai", "anthropic", "openrouter"] = "local"
    local_model: str = "paix-local"
    local_base_url: str = "http://127.0.0.1:1234/v1"
    _local_url = field_validator("local_base_url")(loopback_url)
    tts_provider: Literal["style_bert_vits2", "elevenlabs", "mock"] = "style_bert_vits2"
    stage_port: int = Field(8765, ge=1024, le=65535)
    trace_enabled: bool = False
    rag_enabled: bool = True
    rag_limit: int = Field(4, ge=1, le=10)


class VoiceProfile(StrictConfig):
    schema_version: Literal[1] = 1
    endpoint: str = "http://127.0.0.1:5000"
    _endpoint = field_validator("endpoint")(loopback_url)
    model_id: Literal[0] = 0
    speaker_id: int = Field(0, ge=0)
    language: Literal["JP", "EN", "ZH"] = "EN"
    style: str = Field("Neutral", min_length=1, max_length=100)
    license_reference: str = Field("", max_length=1000)
    assets_approved: bool = False


class AvatarProfile(StrictConfig):
    schema_version: Literal[1] = 1
    renderer: Literal["unity", "live2d"] = "unity"
    motions: dict[str, str] = Field(
        default_factory=lambda: {
            state: state for state in ("idle", "listening", "thinking", "speaking", "interrupted", "error")
        }
    )
    expressions: dict[str, str] = Field(
        default_factory=lambda: {
            state: state for state in ("neutral", "warm", "excited", "playful", "concerned", "shy")
        }
    )


T = TypeVar("T", bound=BaseModel)


def read_json(path: Path, model: type[T]) -> T:
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ConfigFileError(f"{path.name}: $: file exceeds 2 MiB")
        return model.model_validate_json(path.read_text(encoding="utf-8-sig"))
    except ValidationError as exc:
        locations = [
            "$." + ".".join(map(str, error["loc"])) + ": " + error["type"]
            for error in exc.errors(include_input=False, include_context=False)
        ]
        raise ConfigFileError(f"{path.name}: " + "; ".join(locations)) from None
    except (OSError, UnicodeError):
        raise ConfigFileError(f"{path.name}: $: unreadable JSON file") from None


def atomic_json(path: Path, value: object) -> None:
    serialized = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".paix-", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def runtime_values(root: Path) -> dict[str, object]:
    directory = root / "config"
    profile = read_json(directory / "runtime.json", RuntimeProfile)
    voice = read_json(directory / "voice.json", VoiceProfile)
    avatar = read_json(directory / "avatar.json", AvatarProfile)
    return {
        **profile.model_dump(exclude={"schema_version"}),
        "local_tts_base_url": voice.endpoint,
        "local_tts_model_id": voice.model_id,
        "local_tts_voice_id": str(voice.speaker_id),
        "local_tts_language": voice.language,
        "local_tts_style": voice.style,
        "local_tts_assets_approved": voice.assets_approved and bool(voice.license_reference.strip()),
        "avatar_renderer": avatar.renderer,
    }
