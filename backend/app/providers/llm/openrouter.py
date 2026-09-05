from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

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
from app.providers.llm.sse import sse_data

# Backward-compatible test/import name. The parser itself is provider-neutral.
_sse_data = sse_data


class OpenRouterProvider:
    provider_id = "openrouter"
    capabilities = ProviderCapabilities(cost_reporting=True)
    base_url = "https://openrouter.ai/api/v1"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.manifest = ProviderManifest(
            id=self.provider_id,
            display_name="OpenRouter",
            capabilities=self.capabilities,
            required_secret_names=["OPENROUTER_API_KEY"],
            settings_schema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "default": settings.openrouter_model},
                    "temperature": {"type": "number", "minimum": 0, "maximum": 2},
                    "max_tokens": {"type": "integer", "minimum": 1},
                },
            },
        )

    def _key(self) -> str | None:
        env_value = self.settings.openrouter_api_key.get_secret_value() if self.settings.openrouter_api_key else None
        return secret_store.get("OPENROUTER_API_KEY", env_value)

    def configured(self) -> bool:
        return bool(self._key())

    def _headers(self) -> dict[str, str]:
        key = self._key()
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if self.settings.openrouter_http_referer:
            headers["HTTP-Referer"] = self.settings.openrouter_http_referer
        if self.settings.openrouter_title:
            headers["X-OpenRouter-Title"] = self.settings.openrouter_title
        headers["X-OpenRouter-Metadata"] = "enabled"
        return headers

    async def list_models(self) -> list[ModelInfo]:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{self.base_url}/models")
            response.raise_for_status()
        return [
            ModelInfo(
                id=item["id"],
                display_name=item.get("name"),
                provider_id=self.provider_id,
                metadata={"context_length": item.get("context_length"), "pricing": item.get("pricing")},
            )
            for item in response.json().get("data", [])
            if item.get("id")
        ]

    async def health_check(self) -> HealthResult:
        if not self.configured():
            return HealthResult(status="unavailable", message="OPENROUTER_API_KEY is not configured")
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/auth/key", headers=self._headers())
                response.raise_for_status()
        except Exception as exc:
            return HealthResult(status="unavailable", message=f"OpenRouter connection failed: {type(exc).__name__}")
        return HealthResult(
            status="ok", message="OpenRouter is reachable", latency_ms=(time.perf_counter() - started) * 1000
        )

    async def stream_response(
        self, request: CanonicalLLMRequest, cancellation: CancellationToken
    ) -> AsyncIterator[CanonicalLLMEvent]:
        if not self.configured():
            yield CanonicalLLMEvent(
                type="provider.error",
                payload={"code": "not_configured", "message": "OPENROUTER_API_KEY is not configured"},
            )
            return
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "system", "content": request.system_prompt}]
            + [
                {"role": message.role, "content": message.content}
                for message in request.messages
                if message.role in {"user", "assistant"}
            ],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        for option in ("temperature", "top_p", "max_tokens", "stop", "seed", "provider"):
            if option in request.options:
                body[option] = request.options[option]
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": tool.name, "description": tool.description, "parameters": tool.input_schema},
                }
                for tool in request.tools
            ]
        tool_parts: dict[int, dict[str, Any]] = {}
        try:
            yield CanonicalLLMEvent(
                type="response.started", payload={"provider": self.provider_id, "model": request.model}
            )
            async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions", headers=self._headers(), json=body
                ) as response:
                    response.raise_for_status()
                    async for data in sse_data(response.aiter_lines()):
                        if cancellation.cancelled:
                            yield CanonicalLLMEvent(type="response.cancelled")
                            return
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if chunk.get("error"):
                            error = chunk["error"]
                            yield CanonicalLLMEvent(
                                type="provider.error",
                                payload={
                                    "code": str(error.get("code", "provider_error")),
                                    "message": error.get("message", "OpenRouter error"),
                                },
                            )
                            return
                        choices = chunk.get("choices") or []
                        for choice in choices:
                            delta = choice.get("delta") or {}
                            content = delta.get("content")
                            if content:
                                yield CanonicalLLMEvent(type="text.delta", payload={"text": content}, raw=chunk)
                            for call in delta.get("tool_calls") or []:
                                index = int(call.get("index", 0))
                                target = tool_parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
                                target["id"] = call.get("id") or target["id"]
                                function = call.get("function") or {}
                                target["name"] += function.get("name") or ""
                                target["arguments"] += function.get("arguments") or ""
                        usage = chunk.get("usage")
                        if usage:
                            yield CanonicalLLMEvent(
                                type="usage.updated",
                                payload={
                                    "input_tokens": usage.get("prompt_tokens", 0),
                                    "output_tokens": usage.get("completion_tokens", 0),
                                    "cost_usd": usage.get("cost"),
                                },
                                raw=chunk,
                            )
                        routed = {key: chunk.get(key) for key in ("model", "provider") if chunk.get(key)}
                        if routed:
                            request.metadata["routed"] = routed
            for call in tool_parts.values():
                yield CanonicalLLMEvent(type="tool.call", payload=call)
            yield CanonicalLLMEvent(
                type="response.completed",
                payload={"finish_reason": "stop", **request.metadata.get("routed", {"model": request.model})},
            )
        except Exception as exc:
            yield CanonicalLLMEvent(
                type="provider.error", payload={"code": type(exc).__name__, "message": str(exc)[:500]}
            )
