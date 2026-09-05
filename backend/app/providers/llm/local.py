from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import Settings
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


class LMStudioProvider:
    """Strictly loopback LM Studio adapter; it never falls back to a cloud LLM."""

    provider_id = "local"
    capabilities = ProviderCapabilities(tool_calls=False, cost_reporting=False, reasoning_metadata=False)

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self.base_url = settings.local_base_url.rstrip("/")
        self.transport = transport
        self.manifest = ProviderManifest(
            id=self.provider_id,
            display_name="Local LM Studio",
            capabilities=self.capabilities,
            settings_schema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "default": settings.local_model},
                    "temperature": {"type": "number", "minimum": 0, "maximum": 2, "default": 0.75},
                    "max_tokens": {"type": "integer", "minimum": 1, "default": 160},
                },
            },
        )

    def configured(self) -> bool:
        # Settings validation guarantees this URL is loopback-only.
        return bool(self.settings.local_model and self.base_url)

    def _client(self, timeout: httpx.Timeout | float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self.transport)

    async def list_models(self) -> list[ModelInfo]:
        async with self._client(10) as client:
            response = await client.get(f"{self.base_url}/models")
            response.raise_for_status()
        payload = response.json()
        return [
            ModelInfo(
                id=str(item["id"]),
                display_name=str(item.get("id") or item["id"]),
                provider_id=self.provider_id,
                metadata={"owned_by": item.get("owned_by")},
            )
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]

    async def health_check(self) -> HealthResult:
        started = time.perf_counter()
        try:
            models = await self.list_models()
        except Exception as exc:
            return HealthResult(
                status="unavailable",
                message=f"Local LM Studio is not reachable: {type(exc).__name__}",
            )
        model_ids = {model.id for model in models}
        latency_ms = (time.perf_counter() - started) * 1000
        if self.settings.local_model not in model_ids:
            return HealthResult(
                status="degraded",
                message=f"LM Studio is running, but '{self.settings.local_model}' is not loaded",
                latency_ms=latency_ms,
                details={"loaded_models": sorted(model_ids)},
            )
        return HealthResult(
            status="ok",
            message="Local LM Studio model is ready",
            latency_ms=latency_ms,
            details={"model": self.settings.local_model},
        )

    @staticmethod
    def _messages(request: CanonicalLLMRequest) -> list[dict[str, str]]:
        runtime_facts = (
            "\n\n## Current runtime facts\n"
            "There are two separate local components: (1) language generation uses Qwen3.5 4B through LM Studio "
            "on a loopback address; (2) speech recognition uses Faster-Whisper. OpenRouter and other cloud LLMs "
            "are not in use. Text-to-speech is a separate component: ElevenLabs is still online when voice output "
            "is enabled. Never claim that Faster-Whisper runs through LM Studio, or that the entire voice system "
            "is offline or private."
        )
        messages = [{"role": "system", "content": request.system_prompt + runtime_facts}]
        messages.extend(
            {"role": message.role, "content": message.content}
            for message in request.messages
            if message.role in {"user", "assistant"}
        )
        return messages

    async def stream_response(
        self, request: CanonicalLLMRequest, cancellation: CancellationToken
    ) -> AsyncIterator[CanonicalLLMEvent]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": self._messages(request),
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": 0.75,
            "top_p": 0.9,
            "max_tokens": 160,
            # Non-thinking mode is a much better fit for low-latency voice chat.
            "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
        }
        for option in ("temperature", "top_p", "max_tokens", "stop", "seed"):
            if option in request.options:
                body[option] = request.options[option]
        tool_parts: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"
        try:
            yield CanonicalLLMEvent(
                type="response.started",
                payload={"provider": self.provider_id, "model": request.model},
            )
            async with self._client(httpx.Timeout(180, connect=5)) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers={"Content-Type": "application/json"},
                    json=body,
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
                        if not isinstance(chunk, dict):
                            continue
                        error = chunk.get("error")
                        if error:
                            message = (
                                error.get("message", "Local model error") if isinstance(error, dict) else str(error)
                            )
                            yield CanonicalLLMEvent(
                                type="provider.error",
                                payload={"code": "local_model_error", "message": message[:500]},
                            )
                            return
                        for choice in chunk.get("choices") or []:
                            if not isinstance(choice, dict):
                                continue
                            finish_reason = str(choice.get("finish_reason") or finish_reason)
                            delta = choice.get("delta") or {}
                            content = delta.get("content") if isinstance(delta, dict) else None
                            if isinstance(content, str) and content:
                                # Never forward raw chunks: local runtimes can include hidden reasoning fields.
                                yield CanonicalLLMEvent(type="text.delta", payload={"text": content})
                            if isinstance(delta, dict):
                                for call in delta.get("tool_calls") or []:
                                    if not isinstance(call, dict):
                                        continue
                                    index = int(call.get("index", 0))
                                    target = tool_parts.setdefault(
                                        index,
                                        {"id": "", "name": "", "arguments": ""},
                                    )
                                    target["id"] = call.get("id") or target["id"]
                                    function = call.get("function") or {}
                                    if isinstance(function, dict):
                                        target["name"] += function.get("name") or ""
                                        target["arguments"] += function.get("arguments") or ""
                        usage = chunk.get("usage")
                        if isinstance(usage, dict):
                            yield CanonicalLLMEvent(
                                type="usage.updated",
                                payload={
                                    "input_tokens": usage.get("prompt_tokens", 0),
                                    "output_tokens": usage.get("completion_tokens", 0),
                                },
                            )
            for call in tool_parts.values():
                yield CanonicalLLMEvent(type="tool.call", payload=call)
            yield CanonicalLLMEvent(
                type="response.completed",
                payload={"finish_reason": finish_reason, "model": request.model},
            )
        except Exception as exc:
            yield CanonicalLLMEvent(
                type="provider.error",
                payload={
                    "code": type(exc).__name__,
                    "message": (
                        f"Local LM Studio request failed: {str(exc)[:400]}. "
                        "Run scripts/start-local-model.ps1; Paix will not fall back to a cloud model."
                    ),
                },
            )
