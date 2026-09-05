from __future__ import annotations

import json
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


class AnthropicProvider:
    provider_id = "anthropic"
    capabilities = ProviderCapabilities()

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.manifest = ProviderManifest(
            id=self.provider_id,
            display_name="Anthropic Messages",
            capabilities=self.capabilities,
            required_secret_names=["ANTHROPIC_API_KEY"],
            settings_schema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "default": settings.anthropic_model},
                    "max_tokens": {"type": "integer", "minimum": 1, "default": 1024},
                    "temperature": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        )

    def _key(self) -> str | None:
        env_value = self.settings.anthropic_api_key.get_secret_value() if self.settings.anthropic_api_key else None
        return secret_store.get("ANTHROPIC_API_KEY", env_value)

    def configured(self) -> bool:
        return bool(self._key())

    def _client(self):
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise RuntimeError("Install the 'anthropic' backend dependency") from exc
        key = self._key()
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")
        return AsyncAnthropic(api_key=key)

    async def list_models(self) -> list[ModelInfo]:
        if not self.configured():
            return [
                ModelInfo(id=self.settings.anthropic_model, provider_id=self.provider_id, metadata={"manual": True})
            ]
        try:
            response = await self._client().models.list(limit=100)
            return [
                ModelInfo(id=model.id, display_name=getattr(model, "display_name", None), provider_id=self.provider_id)
                for model in response.data
            ]
        except Exception:
            return [
                ModelInfo(id=self.settings.anthropic_model, provider_id=self.provider_id, metadata={"manual": True})
            ]

    async def health_check(self) -> HealthResult:
        if not self.configured():
            return HealthResult(status="unavailable", message="ANTHROPIC_API_KEY is not configured")
        started = time.perf_counter()
        try:
            await self._client().models.list(limit=1)
        except Exception as exc:
            return HealthResult(status="unavailable", message=f"Anthropic connection failed: {type(exc).__name__}")
        return HealthResult(
            status="ok", message="Anthropic is reachable", latency_ms=(time.perf_counter() - started) * 1000
        )

    async def stream_response(
        self, request: CanonicalLLMRequest, cancellation: CancellationToken
    ) -> AsyncIterator[CanonicalLLMEvent]:
        if not self.configured():
            yield CanonicalLLMEvent(
                type="provider.error",
                payload={"code": "not_configured", "message": "ANTHROPIC_API_KEY is not configured"},
            )
            return
        kwargs: dict[str, Any] = {
            "model": request.model,
            "system": request.system_prompt,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
                if message.role in {"user", "assistant"}
            ],
            "max_tokens": int(request.options.get("max_tokens", 1024)),
        }
        for option in ("temperature", "top_p", "top_k", "stop_sequences"):
            if option in request.options:
                kwargs[option] = request.options[option]
        if request.tools:
            kwargs["tools"] = [
                {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
                for tool in request.tools
            ]
        tool_parts: dict[int, dict[str, Any]] = {}
        try:
            yield CanonicalLLMEvent(
                type="response.started", payload={"provider": self.provider_id, "model": request.model}
            )
            async with self._client().messages.stream(**kwargs) as stream:
                async for event in stream:
                    if cancellation.cancelled:
                        yield CanonicalLLMEvent(type="response.cancelled")
                        return
                    event_type = getattr(event, "type", "")
                    raw = event.model_dump(mode="json") if hasattr(event, "model_dump") else None
                    if event_type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if getattr(block, "type", None) == "tool_use":
                            tool_parts[int(getattr(event, "index", 0))] = {
                                "id": getattr(block, "id", ""),
                                "name": getattr(block, "name", ""),
                                "arguments": "",
                                "initial_input": getattr(block, "input", {}) or {},
                                "raw": raw,
                            }
                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if getattr(delta, "type", None) == "text_delta":
                            yield CanonicalLLMEvent(
                                type="text.delta", payload={"text": getattr(delta, "text", "")}, raw=raw
                            )
                        elif getattr(delta, "type", None) == "input_json_delta":
                            index = int(getattr(event, "index", 0))
                            target = tool_parts.setdefault(
                                index,
                                {"id": "", "name": "", "arguments": "", "initial_input": {}, "raw": raw},
                            )
                            target["arguments"] += getattr(delta, "partial_json", "") or ""
                    elif event_type == "content_block_stop":
                        target = tool_parts.pop(int(getattr(event, "index", 0)), None)
                        if target:
                            arguments = target["arguments"]
                            if not arguments:
                                arguments = json.dumps(target["initial_input"], separators=(",", ":"))
                            yield CanonicalLLMEvent(
                                type="tool.call",
                                payload={"id": target["id"], "name": target["name"], "arguments": arguments},
                                raw=target["raw"] or raw,
                            )
                message = await stream.get_final_message()
            usage = getattr(message, "usage", None)
            if usage:
                yield CanonicalLLMEvent(
                    type="usage.updated",
                    payload={
                        "input_tokens": getattr(usage, "input_tokens", 0),
                        "output_tokens": getattr(usage, "output_tokens", 0),
                    },
                )
            yield CanonicalLLMEvent(
                type="response.completed",
                payload={
                    "finish_reason": getattr(message, "stop_reason", "stop"),
                    "model": getattr(message, "model", request.model),
                },
            )
        except Exception as exc:
            yield CanonicalLLMEvent(
                type="provider.error", payload={"code": type(exc).__name__, "message": str(exc)[:500]}
            )
