from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "[REDACTED]"
KEYRING_SERVICE = "Paix Local Companion"
LEGACY_KEYRING_SERVICES = ("Sylphiette Local Companion",)
ALLOWED_SECRET_NAMES = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "ELEVENLABS_API_KEY",
}
_SENSITIVE_KEYS = re.compile(
    r"(?:authorization|api[-_]?key|access[-_]?token|refresh[-_]?token|password|secret|cookie)",
    re.IGNORECASE,
)
_SECRET_PATTERNS = [
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-(?:proj-|ant-|or-)?[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bsk_[A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
    re.compile(r"\bxi-[A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;\"']+"),
]


def redact_text(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            result = pattern.sub(r"\1" + REDACTED, result)
        else:
            result = pattern.sub(REDACTED, result)
    return result


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {str(key): REDACTED if _SENSITIVE_KEYS.search(str(key)) else redact(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [redact(item) for item in value]
    return value


def redacted_json(value: Any) -> str:
    return json.dumps(redact(value), ensure_ascii=False, indent=2, default=str)


class SecretStore:
    """Session secrets plus optional OS-keyring persistence.

    Values are never returned by API serialization. On Windows, the installed
    keyring backend stores persistent values in Windows Credential Manager.
    """

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def set(self, name: str, value: str | None) -> None:
        normalized = name.upper()
        if normalized not in ALLOWED_SECRET_NAMES:
            raise ValueError(f"Unsupported secret name: {normalized}")
        if value:
            self._values[normalized] = value
        else:
            self._values.pop(normalized, None)

    def get(self, name: str, fallback: str | None = None) -> str | None:
        normalized = name.upper()
        session_value = self._values.get(normalized)
        if session_value:
            return session_value
        if fallback and fallback.strip():
            return fallback.strip()
        if normalized not in ALLOWED_SECRET_NAMES:
            return None
        try:
            import keyring

            for service in (KEYRING_SERVICE, *LEGACY_KEYRING_SERVICES):
                value = keyring.get_password(service, normalized)
                if value and value.strip():
                    return value.strip()
            return None
        except Exception:
            return None

    def set_persistent(self, name: str, value: str | None) -> None:
        normalized = name.upper()
        if normalized not in ALLOWED_SECRET_NAMES:
            raise ValueError(f"Unsupported secret name: {normalized}")
        try:
            import keyring
            from keyring.errors import PasswordDeleteError

            if value and value.strip():
                keyring.set_password(KEYRING_SERVICE, normalized, value.strip())
            else:
                for service in (KEYRING_SERVICE, *LEGACY_KEYRING_SERVICES):
                    try:
                        keyring.delete_password(service, normalized)
                    except PasswordDeleteError:
                        pass
        except Exception as exc:
            raise RuntimeError("Windows Credential Manager is unavailable") from exc

    def configured(self, name: str, fallback: str | None = None) -> bool:
        return bool(self.get(name, fallback))


secret_store = SecretStore()
