from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_provider: str | None = None
    openai_model: str | None = None
    anthropic_model: str | None = None
    openrouter_model: str | None = None
    elevenlabs_voice_id: str | None = None
    elevenlabs_model_id: str | None = None
    elevenlabs_output_format: str | None = None
    stt_model: str | None = None
    stt_device: Literal["auto", "cuda", "cpu"] | None = None
    stt_compute_type: str | None = None
    vad_threshold: float | None = Field(default=None, ge=0, le=1)
    session_secrets: dict[str, str | None] = Field(default_factory=dict)
    persistent_secrets: dict[str, str | None] = Field(default_factory=dict)

    @field_validator("session_secrets", "persistent_secrets")
    @classmethod
    def allowed_secrets(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        allowed = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "ELEVENLABS_API_KEY"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"Unsupported secret names: {', '.join(sorted(unknown))}")
        return value


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=240)


class MemoryCreate(BaseModel):
    category: str = Field(default="general", min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=20_000)
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.5, ge=0, le=1)
    source_message_id: str | None = None
    status: Literal["pending", "approved", "rejected", "archived"] = "pending"


class MemoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, min_length=1, max_length=80)
    content: str | None = Field(default=None, min_length=1, max_length=20_000)
    importance: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: Literal["pending", "approved", "rejected", "archived"] | None = None


class MemoryImport(BaseModel):
    items: list[MemoryCreate] = Field(max_length=10_000)


class VoiceSampleRequest(BaseModel):
    text: str = Field(
        default=(
            "Welcome back, Poom. I kept everything ready while you were away. "
            "Shall we continue building, or would you like a quiet moment first?"
        ),
        min_length=1,
        max_length=2_000,
    )
    voice_id: str = Field(min_length=1, max_length=200)
    model_id: str = Field(default="eleven_flash_v2_5", min_length=1, max_length=200)
    output_format: str = Field(default="mp3_44100_128", min_length=1, max_length=80)
    voice_settings: dict[str, Any] = Field(default_factory=dict)


class ToolExecuteRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False
