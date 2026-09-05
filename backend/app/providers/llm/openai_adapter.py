from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from app.core.config import Settings
from app.core.security import secret_store
from app.providers.llm.base import (
    CancellationToken,
    CanonicalLLMEvent,
    CanonicalLLMRequest,
    HealthResult,
    ModelInfo,
    ProviderCapabilities,
    ProviderManifest,
)


class OpenAIProvider:
    provider_id = "openai"
    capabilities = ProviderCapabilities()
    _allowed_options = {"temperature", "top_p", "max_output_tokens", "reasoning", "text", "service_tier"}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.manifest = ProviderManifest(
            id=self.provider_id,
            display_name="OpenAI Responses",
            capabilities=self.capabilities,
            required_secret_names=["OPENAI_API_KEY"],
            settings_schema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "default": settings.openai_model},
                    "temperature": {"type": "number", "minimum": 0, "maximum": 2},
                    "max_output_tokens": {"type": "integer", "minimum": 1},
                },
            },
        )

    def _key(self) -> str | None:
        env_value = self.settings.openai_api_key.get_secret_value() if self.settings.openai_api_key else None
        return secret_store.get("OPENAI_API_KEY", env_value)

    def configured(self) -> bool:
        return bool(self._key())

    def _client(self):
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError("Install the 'openai' backend dependency") from exc
        key = self._key()
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        return AsyncOpenAI(api_key=key)

    async def list_models(self) -> list[ModelInfo]:
        if not self.configured():
            return [ModelInfo(id=self.settings.openai_model, provider_id=self.provider_id, metadata={"manual": True})]
        response = await self._client().models.list()
        return sorted(
            [ModelInfo(id=item.id, provider_id=self.provider_id) for item in response.data], key=lambda model: model.id
        )

    async def health_check(self) -> HealthResult:
        if not self.configured():
            return HealthResult(status="unavailable", message="OPENAI_API_KEY is not configured")
        started = time.perf_counter()
        try:
            await self._client().models.list()
        except Exception as exc:  # provider exceptions vary by SDK version
            return HealthResult(status="unavailable", message=f"OpenAI connection failed: {type(exc).__name__}")
        return HealthResult(
            status="ok", message="OpenAI is reachable", latency_ms=(time.perf_counter() - started) * 1000
        )

    async def stream_response(
        self, request: CanonicalLLMRequest, cancellation: CancellationToken
    ) -> AsyncIterator[CanonicalLLMEvent]:
        if not self.configured():
            yield CanonicalLLMEvent(
                type="provider.error", payload={"code": "not_configured", "message": "OPENAI_API_KEY is not configured"}
            )
            return
        kwargs: dict[str, Any] = {
            "model": request.model,
            "instructions": request.system_prompt,
            "input": [
                {"role": message.role, "content": message.content}
                for message in request.messages
                if message.role in {"user", "assistant"}
            ],
            "stream": True,
        }
        kwargs.update({key: value for key, value in request.options.items() if key in self._allowed_options})
        if request.tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                }
                for tool in request.tools
            ]
        try:
            stream = await self._client().responses.create(**kwargs)
            yield CanonicalLLMEvent(
                type="response.started", payload={"provider": self.provider_id, "model": request.model}
            )
            async for event in stream:
                if cancellation.cancelled:
                    close = getattr(stream, "close", None)
                    if close:
                        result = close()
                        if hasattr(result, "__await__"):
                            await result
                    yield CanonicalLLMEvent(type="response.cancelled")
                    return
                event_type = getattr(event, "type", "")
                raw = event.model_dump(mode="json") if hasattr(event, "model_dump") else None
                if event_type == "response.output_text.delta":
                    yield CanonicalLLMEvent(type="text.delta", payload={"text": getattr(event, "delta", "")}, raw=raw)
                elif event_type == "response.output_item.done":
                    item = getattr(event, "item", None)
                    if getattr(item, "type", None) == "function_call":
                        yield CanonicalLLMEvent(
                            type="tool.call",
                            payload={
                                "id": getattr(item, "call_id", None),
                                "name": getattr(item, "name", ""),
                                "arguments": getattr(item, "arguments", "{}"),
                            },
                            raw=raw,
                        )
                elif event_type == "response.completed":
                    response = getattr(event, "response", None)
                    usage = getattr(response, "usage", None)
                    if usage:
                        yield CanonicalLLMEvent(
                            type="usage.updated",
                            payload={
                                "input_tokens": getattr(usage, "input_tokens", 0),
                                "output_tokens": getattr(usage, "output_tokens", 0),
                            },
                            raw=raw,
                        )
                    yield CanonicalLLMEvent(
                        type="response.completed",
                        payload={"finish_reason": "stop", "model": getattr(response, "model", request.model)},
                        raw=raw,
                    )
                elif event_type in {"response.failed", "error"}:
                    error = getattr(event, "error", None)
                    yield CanonicalLLMEvent(
                        type="provider.error",
                        payload={"code": getattr(error, "code", "provider_error"), "message": str(error)},
                        raw=raw,
                    )
        except Exception as exc:
            yield CanonicalLLMEvent(
                type="provider.error", payload={"code": type(exc).__name__, "message": str(exc)[:500]}
            )
