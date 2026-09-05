from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

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


class MockProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(cost_reporting=True)

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.manifest = ProviderManifest(
            id=self.provider_id,
            display_name="Mock (free, offline)",
            capabilities=self.capabilities,
            required_secret_names=[],
            settings_schema={
                "type": "object",
                "properties": {
                    "latency_ms": {"type": "integer", "minimum": 0, "maximum": 5000, "default": 25},
                    "failure_mode": {
                        "type": "string",
                        "enum": ["none", "timeout", "rate_limit", "malformed"],
                        "default": "none",
                    },
                },
            },
        )

    def configured(self) -> bool:
        return True

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id=self.settings.mock_model, display_name="Paix Mock", provider_id=self.provider_id)]

    async def health_check(self) -> HealthResult:
        return HealthResult(status="ok", message="Offline deterministic provider is ready")

    @staticmethod
    def _answer(request: CanonicalLLMRequest) -> str:
        last = next((message.content for message in reversed(request.messages) if message.role == "user"), "")
        if not last:
            return "I’m here, Poom. What would you like to work on together?"
        lowered = last.casefold()
        if "time" in lowered:
            return "I can check the local time with the registered time tool when tool calling is enabled."
        if any(word in lowered for word in ("hello", "hi", "hey")):
            return "Hello, Poom. I’m glad you’re here. What shall we focus on?"
        preview = last.strip().replace("\n", " ")[:180]
        return f"I’m with you, Poom. You said: “{preview}” Let’s take it one clear step at a time."

    async def stream_response(
        self, request: CanonicalLLMRequest, cancellation: CancellationToken
    ) -> AsyncIterator[CanonicalLLMEvent]:
        latency = min(max(int(request.options.get("latency_ms", 25)), 0), 5000) / 1000
        failure = str(request.options.get("failure_mode", "none"))
        yield CanonicalLLMEvent(type="response.started", payload={"model": request.model, "provider": self.provider_id})
        if failure == "rate_limit":
            yield CanonicalLLMEvent(
                type="provider.error", payload={"code": "rate_limit", "message": "Simulated rate limit"}
            )
            return
        if failure == "timeout":
            try:
                await asyncio.wait_for(cancellation.wait(), timeout=10)
            except TimeoutError:
                yield CanonicalLLMEvent(
                    type="provider.error", payload={"code": "timeout", "message": "Simulated timeout"}
                )
            else:
                yield CanonicalLLMEvent(type="response.cancelled")
            return
        if failure == "malformed":
            yield CanonicalLLMEvent(
                type="provider.error", payload={"code": "malformed_event", "message": "Simulated malformed event"}
            )
            return

        answer = self._answer(request)
        chunks = re.findall(r"\S+\s*", answer)
        for chunk in chunks:
            if cancellation.cancelled:
                yield CanonicalLLMEvent(type="response.cancelled")
                return
            if latency:
                await asyncio.sleep(latency)
            yield CanonicalLLMEvent(type="text.delta", payload={"text": chunk})

        input_tokens = max(1, (len(request.system_prompt) + sum(len(m.content) for m in request.messages)) // 4)
        output_tokens = max(1, len(answer) // 4)
        yield CanonicalLLMEvent(
            type="usage.updated",
            payload={"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": 0.0, "estimated": False},
        )
        yield CanonicalLLMEvent(
            type="response.completed", payload={"finish_reason": "stop", "model": request.model, "text": answer}
        )
