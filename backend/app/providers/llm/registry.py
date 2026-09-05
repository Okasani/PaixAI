from __future__ import annotations

from app.core.config import Settings, get_settings
from app.providers.llm.anthropic_adapter import AnthropicProvider
from app.providers.llm.base import LLMProvider
from app.providers.llm.local import LMStudioProvider
from app.providers.llm.mock import MockProvider
from app.providers.llm.openai_adapter import OpenAIProvider
from app.providers.llm.openrouter import OpenRouterProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}

    def register(self, provider: LLMProvider) -> None:
        if provider.provider_id in self._providers:
            raise ValueError(f"Provider already registered: {provider.provider_id}")
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> LLMProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"Unknown provider: {provider_id}") from exc

    def all(self) -> list[LLMProvider]:
        return list(self._providers.values())


def build_provider_registry(settings: Settings | None = None) -> ProviderRegistry:
    resolved = settings or get_settings()
    registry = ProviderRegistry()
    registry.register(MockProvider(resolved))
    registry.register(LMStudioProvider(resolved))
    registry.register(OpenAIProvider(resolved))
    registry.register(AnthropicProvider(resolved))
    registry.register(OpenRouterProvider(resolved))
    return registry
