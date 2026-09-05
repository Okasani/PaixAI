import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_optional_websocket_origins_accept_comma_separated_values(monkeypatch) -> None:
    monkeypatch.setenv(
        "PAIX_ALLOWED_WEBSOCKET_ORIGINS",
        "http://127.0.0.1:9000,http://localhost:9000",
    )

    settings = Settings(_env_file=None)

    assert settings.allowed_websocket_origins == ["http://127.0.0.1:9000", "http://localhost:9000"]


def test_voice_provider_and_model_accept_prefixed_environment_names(monkeypatch) -> None:
    monkeypatch.setenv("PAIX_DEFAULT_PROVIDER", "openai")
    monkeypatch.setenv("PAIX_OPENAI_MODEL", "voice-test-model")

    settings = Settings(_env_file=None)

    assert settings.default_provider == "openai"
    assert settings.openai_model == "voice-test-model"


def test_legacy_sylphiette_environment_names_remain_compatible(monkeypatch) -> None:
    monkeypatch.delenv("PAIX_DEFAULT_PROVIDER", raising=False)
    monkeypatch.setenv("SYLPHIETTE_DEFAULT_PROVIDER", "anthropic")

    settings = Settings(_env_file=None)

    assert settings.default_provider == "anthropic"


def test_v02_defaults_to_a_loopback_local_model(monkeypatch) -> None:
    for name in ("PAIX_DEFAULT_PROVIDER", "SYLPHIETTE_DEFAULT_PROVIDER", "DEFAULT_PROVIDER"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.default_provider == "local"
    assert settings.local_model == "paix-local"
    assert settings.local_base_url == "http://127.0.0.1:1234/v1"


def test_local_model_endpoint_rejects_non_loopback_hosts(monkeypatch) -> None:
    monkeypatch.setenv("PAIX_LOCAL_BASE_URL", "https://models.example/v1")

    with pytest.raises(ValidationError, match="loopback"):
        Settings(_env_file=None)


def test_live2d_stage_stream_rejects_non_loopback_hosts(monkeypatch) -> None:
    monkeypatch.setenv("PAIX_STAGE_HOST", "192.0.2.10")

    with pytest.raises(ValidationError, match="loopback"):
        Settings(_env_file=None)
