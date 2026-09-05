import sys
from types import SimpleNamespace

from app.core.security import REDACTED, SecretStore, redact, redact_text


def test_redacts_provider_key_shapes_and_headers() -> None:
    token = "abcdefghijklmnopqrstuvwxyz"
    value = f"Authorization: Bearer {token} sk-proj-{token} sk_ant_style_is_not_real sk_{token} xi-{token}"
    result = redact_text(value)

    assert "abcdefghijklmnopqrstuvwxyz" not in result
    assert result.count(REDACTED) >= 3


def test_redacts_sensitive_mapping_recursively() -> None:
    result = redact({"authorization": "Bearer secret-value", "nested": [{"api_key": "secret"}]})

    assert result == {"authorization": REDACTED, "nested": [{"api_key": REDACTED}]}


def test_secret_store_reads_legacy_keyring_service(monkeypatch) -> None:
    def get_password(service: str, _name: str) -> str | None:
        return "legacy-secret" if service == "Sylphiette Local Companion" else None

    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_password=get_password))

    assert SecretStore().get("OPENAI_API_KEY") == "legacy-secret"
