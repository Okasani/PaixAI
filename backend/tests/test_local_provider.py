from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.providers.llm.base import CancellationToken, CanonicalLLMRequest, CanonicalMessage
from app.providers.llm.local import LMStudioProvider


@pytest.mark.asyncio
async def test_local_provider_streams_text_without_exposing_reasoning() -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "paix-local", "owned_by": "local"}]})
        captured.update(json.loads(request.content))
        stream = (
            'data: {"choices":[{"delta":{"reasoning_content":"private","content":"My name "}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"is Paix."},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":10,"completion_tokens":4}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})

    provider = LMStudioProvider(Settings(_env_file=None), transport=httpx.MockTransport(handler))
    request = CanonicalLLMRequest(
        model="paix-local",
        system_prompt="Your name is Paix.",
        messages=[CanonicalMessage(role="user", content="What is your name?")],
    )

    health = await provider.health_check()
    events = [event async for event in provider.stream_response(request, CancellationToken())]

    assert health.status == "ok"
    assert "".join(event.payload.get("text", "") for event in events) == "My name is Paix."
    assert all(event.raw is None for event in events)
    assert [event.type for event in events] == [
        "response.started",
        "text.delta",
        "text.delta",
        "usage.updated",
        "response.completed",
    ]
    assert captured["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["reasoning_effort"] == "none"
    assert captured["model"] == "paix-local"
    assert "language generation uses Qwen3.5 4B through LM Studio" in captured["messages"][0]["content"]


@pytest.mark.asyncio
async def test_local_provider_reports_missing_loaded_model() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    provider = LMStudioProvider(Settings(_env_file=None), transport=httpx.MockTransport(handler))

    health = await provider.health_check()

    assert health.status == "degraded"
    assert "not loaded" in health.message


@pytest.mark.asyncio
async def test_local_provider_failure_is_reported_without_fallback() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("local server offline", request=request)

    provider = LMStudioProvider(Settings(_env_file=None), transport=httpx.MockTransport(handler))
    request = CanonicalLLMRequest(
        model="paix-local",
        system_prompt="Your name is Paix.",
        messages=[CanonicalMessage(role="user", content="Hello")],
    )

    events = [event async for event in provider.stream_response(request, CancellationToken())]

    assert [event.type for event in events] == ["response.started", "provider.error"]
    assert "will not fall back to a cloud model" in events[-1].payload["message"]
