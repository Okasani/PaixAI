from __future__ import annotations

from typing import Generic, Protocol, TypeVar


class ManifestProvider(Protocol):
    provider_id: str
    manifest: object


T = TypeVar("T", bound=ManifestProvider)


class ComponentRegistry(Generic[T]):
    """Shared extension point for STT, TTS, memory, tools, and future avatars."""

    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def register(self, provider: T) -> None:
        if provider.provider_id in self._items:
            raise ValueError(f"Component already registered: {provider.provider_id}")
        self._items[provider.provider_id] = provider

    def get(self, provider_id: str) -> T:
        try:
            return self._items[provider_id]
        except KeyError as exc:
            raise KeyError(f"Unknown component: {provider_id}") from exc

    def all(self) -> list[T]:
        return list(self._items.values())
