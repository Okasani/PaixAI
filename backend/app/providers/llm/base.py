from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ProviderCapabilities(BaseModel):
    streaming: bool = True
    tool_calls: bool = True
    model_discovery: bool = True
    usage_reporting: bool = True
    cost_reporting: bool = False
    reasoning_metadata: bool = False


class ProviderManifest(BaseModel):
    id: str
    display_name: str
    capabilities: ProviderCapabilities
    settings_schema: dict[str, Any] = Field(default_factory=dict)
    required_secret_names: list[str] = Field(default_factory=list)


class ModelInfo(BaseModel):
    id: str
    display_name: str | None = None
    provider_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthResult(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    message: str
    latency_ms: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class CanonicalMessage(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class CanonicalToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class CanonicalLLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    system_prompt: str
    messages: list[CanonicalMessage]
    tools: list[CanonicalToolDefinition] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


CanonicalEventType = Literal[
    "response.started",
    "text.delta",
    "tool.call",
    "usage.updated",
    "response.completed",
    "response.cancelled",
    "provider.error",
]


class CanonicalLLMEvent(BaseModel):
    type: CanonicalEventType
    payload: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] | None = None


class CancellationToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise asyncio.CancelledError


@runtime_checkable
class LLMProvider(Protocol):
    provider_id: str
    capabilities: ProviderCapabilities
    manifest: ProviderManifest

    async def list_models(self) -> list[ModelInfo]: ...

    async def health_check(self) -> HealthResult: ...

    def configured(self) -> bool: ...

    async def stream_response(
        self, request: CanonicalLLMRequest, cancellation: CancellationToken
    ) -> AsyncIterator[CanonicalLLMEvent]: ...
