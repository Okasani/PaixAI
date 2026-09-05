from __future__ import annotations

from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Paix"
    app_version: str = "0.3.0"
    environment: Literal["development", "test", "production"] = "development"
    host: str = Field("127.0.0.1", validation_alias=AliasChoices("PAIX_HOST", "SYLPHIETTE_HOST", "HOST"))
    port: int = Field(8000, validation_alias=AliasChoices("PAIX_PORT", "SYLPHIETTE_PORT", "PORT"))
    log_level: str = Field("INFO", validation_alias=AliasChoices("PAIX_LOG_LEVEL", "SYLPHIETTE_LOG_LEVEL", "LOG_LEVEL"))
    database_url: str = Field(
        f"sqlite+aiosqlite:///{(PROJECT_ROOT / 'data' / 'paix.db').as_posix()}",
        validation_alias=AliasChoices("PAIX_DATABASE_URL", "SYLPHIETTE_DATABASE_URL", "DATABASE_URL"),
    )
    persona_dir: Path = PROJECT_ROOT / "config" / "persona"
    allowed_websocket_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "PAIX_ALLOWED_WEBSOCKET_ORIGINS",
            "SYLPHIETTE_ALLOWED_WEBSOCKET_ORIGINS",
            "ALLOWED_WEBSOCKET_ORIGINS",
        ),
    )
    max_request_bytes: int = Field(
        2 * 1024 * 1024,
        validation_alias=AliasChoices("PAIX_MAX_REQUEST_BYTES", "SYLPHIETTE_MAX_REQUEST_BYTES", "MAX_REQUEST_BYTES"),
    )
    max_audio_bytes: int = Field(
        25 * 1024 * 1024,
        validation_alias=AliasChoices("PAIX_MAX_AUDIO_BYTES", "SYLPHIETTE_MAX_AUDIO_BYTES", "MAX_AUDIO_BYTES"),
    )
    stage_host: str = Field("127.0.0.1", validation_alias="PAIX_STAGE_HOST")
    stage_port: int = Field(8765, ge=1024, le=65535, validation_alias="PAIX_STAGE_PORT")
    recent_turn_limit: int = 16
    memory_retrieval_limit: int = 8

    default_provider: str = Field(
        "local",
        validation_alias=AliasChoices("PAIX_DEFAULT_PROVIDER", "SYLPHIETTE_DEFAULT_PROVIDER", "DEFAULT_PROVIDER"),
    )
    local_model: str = Field(
        "paix-local",
        validation_alias=AliasChoices("PAIX_LOCAL_MODEL", "SYLPHIETTE_LOCAL_MODEL", "LOCAL_MODEL"),
    )
    local_base_url: str = Field(
        "http://127.0.0.1:1234/v1",
        validation_alias=AliasChoices(
            "PAIX_LOCAL_BASE_URL",
            "SYLPHIETTE_LOCAL_BASE_URL",
            "LOCAL_BASE_URL",
        ),
    )
    mock_model: str = Field(
        "paix-mock-1", validation_alias=AliasChoices("PAIX_MOCK_MODEL", "SYLPHIETTE_MOCK_MODEL", "MOCK_MODEL")
    )
    openai_model: str = Field(
        "gpt-5-mini", validation_alias=AliasChoices("PAIX_OPENAI_MODEL", "SYLPHIETTE_OPENAI_MODEL", "OPENAI_MODEL")
    )
    anthropic_model: str = Field(
        "claude-sonnet-4-5",
        validation_alias=AliasChoices("PAIX_ANTHROPIC_MODEL", "SYLPHIETTE_ANTHROPIC_MODEL", "ANTHROPIC_MODEL"),
    )
    openrouter_model: str = Field(
        "openai/gpt-5-mini",
        validation_alias=AliasChoices("PAIX_OPENROUTER_MODEL", "SYLPHIETTE_OPENROUTER_MODEL", "OPENROUTER_MODEL"),
    )
    openrouter_http_referer: str | None = Field(None, validation_alias="OPENROUTER_HTTP_REFERER")
    openrouter_title: str = Field("Paix", validation_alias=AliasChoices("OPENROUTER_APP_TITLE", "OPENROUTER_TITLE"))

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    elevenlabs_api_key_file: Path | None = PROJECT_ROOT / ".secrets" / "elevenlabs.key"
    elevenlabs_voice_id: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "PAIX_ELEVENLABS_VOICE_ID", "SYLPHIETTE_ELEVENLABS_VOICE_ID", "ELEVENLABS_VOICE_ID"
        ),
    )
    elevenlabs_model_id: str = Field(
        "eleven_flash_v2_5",
        validation_alias=AliasChoices("PAIX_ELEVENLABS_MODEL", "SYLPHIETTE_ELEVENLABS_MODEL", "ELEVENLABS_MODEL_ID"),
    )
    elevenlabs_output_format: str = Field(
        "pcm_24000",
        validation_alias=AliasChoices(
            "PAIX_TTS_OUTPUT_FORMAT", "SYLPHIETTE_TTS_OUTPUT_FORMAT", "ELEVENLABS_OUTPUT_FORMAT"
        ),
    )

    stt_model: str = Field(
        "small.en", validation_alias=AliasChoices("PAIX_STT_MODEL", "SYLPHIETTE_STT_MODEL", "STT_MODEL")
    )
    stt_device: Literal["auto", "cuda", "cpu"] = Field(
        "auto", validation_alias=AliasChoices("PAIX_STT_DEVICE", "SYLPHIETTE_STT_DEVICE", "STT_DEVICE")
    )
    stt_compute_type: str = Field(
        "auto",
        validation_alias=AliasChoices("PAIX_STT_COMPUTE_TYPE", "SYLPHIETTE_STT_COMPUTE_TYPE", "STT_COMPUTE_TYPE"),
    )
    stt_language: str = "en"
    vad_threshold: float = Field(
        0.5, validation_alias=AliasChoices("PAIX_VAD_THRESHOLD", "SYLPHIETTE_VAD_THRESHOLD", "VAD_THRESHOLD")
    )
    vad_silence_ms: int = Field(
        900,
        ge=300,
        le=5_000,
        validation_alias=AliasChoices("PAIX_VAD_SILENCE_MS", "SYLPHIETTE_VAD_SILENCE_MS", "VAD_SILENCE_MS"),
    )
    max_utterance_seconds: float = Field(
        30.0,
        ge=5.0,
        le=300.0,
        validation_alias=AliasChoices(
            "PAIX_MAX_UTTERANCE_SECONDS", "SYLPHIETTE_MAX_UTTERANCE_SECONDS", "MAX_UTTERANCE_SECONDS"
        ),
    )

    @field_validator("allowed_websocket_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("local_base_url", mode="after")
    @classmethod
    def local_model_endpoint_must_be_loopback(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("local model endpoint must be a plain loopback HTTP URL")
        host = parsed.hostname
        is_loopback = host == "localhost"
        if host and not is_loopback:
            try:
                is_loopback = ip_address(host).is_loopback
            except ValueError:
                is_loopback = False
        if not is_loopback:
            raise ValueError("local model endpoint must use localhost or a loopback IP address")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("local model endpoint has an invalid port") from exc
        return value.rstrip("/")

    @field_validator("stage_host", mode="after")
    @classmethod
    def stage_host_must_be_loopback(cls, value: str) -> str:
        host = value.strip()
        if host == "localhost":
            return host
        try:
            is_loopback = ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise ValueError("Live2D stage host must use localhost or a loopback IP address")
        return host

    @field_validator("elevenlabs_api_key_file", mode="after")
    @classmethod
    def resolve_secret_file(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            return PROJECT_ROOT / value
        return value

    def safe_dict(self) -> dict[str, object]:
        data = self.model_dump(
            exclude={
                "openai_api_key",
                "anthropic_api_key",
                "openrouter_api_key",
                "elevenlabs_api_key",
            }
        )
        from app.core.security import secret_store

        def present(name: str, value: SecretStr | None) -> bool:
            fallback = value.get_secret_value().strip() if value else None
            return secret_store.configured(name, fallback)

        file_present = False
        if self.elevenlabs_api_key_file:
            try:
                file_present = (
                    self.elevenlabs_api_key_file.is_file() and 0 < self.elevenlabs_api_key_file.stat().st_size <= 16_384
                )
            except OSError:
                file_present = False
        data["keys_configured"] = {
            "OPENAI_API_KEY": present("OPENAI_API_KEY", self.openai_api_key),
            "ANTHROPIC_API_KEY": present("ANTHROPIC_API_KEY", self.anthropic_api_key),
            "OPENROUTER_API_KEY": present("OPENROUTER_API_KEY", self.openrouter_api_key),
            "ELEVENLABS_API_KEY": present("ELEVENLABS_API_KEY", self.elevenlabs_api_key) or file_present,
        }
        data["persona_dir"] = str(self.persona_dir)
        data["elevenlabs_api_key_file"] = str(self.elevenlabs_api_key_file) if self.elevenlabs_api_key_file else None
        return data


@lru_cache
def get_settings() -> Settings:
    return Settings()
