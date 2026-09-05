from __future__ import annotations

import pytest

from app.core.config import Settings
from app.providers.llm.base import CancellationToken, CanonicalLLMRequest, CanonicalMessage
from app.providers.llm.mock import MockProvider


@pytest.mark.asyncio
async def test_mock_provider_streams_canonical_lifecycle() -> None:
    provider = MockProvider(Settings())
    request = CanonicalLLMRequest(
        model="paix-mock-1",
        system_prompt="You are Paix.",
        messages=[CanonicalMessage(role="user", content="Hello")],
        options={"latency_ms": 0},
    )

    events = [event async for event in provider.stream_response(request, CancellationToken())]

    assert events[0].type == "response.started"
    assert events[-1].type == "response.completed"
    assert any(event.type == "text.delta" for event in events)
    assert any(event.type == "usage.updated" for event in events)
    assert "Hello, Poom" in "".join(
        str(event.payload.get("text", "")) for event in events if event.type == "text.delta"
    )


@pytest.mark.asyncio
async def test_mock_provider_cancels_without_late_completion() -> None:
    provider = MockProvider(Settings())
    token = CancellationToken()
    request = CanonicalLLMRequest(
        model="paix-mock-1",
        system_prompt="system",
        messages=[CanonicalMessage(role="user", content="hello")],
        options={"latency_ms": 0},
    )
    stream = provider.stream_response(request, token)
    first = await anext(stream)
    token.cancel()
    remaining = [event async for event in stream]

    assert first.type == "response.started"
    assert [event.type for event in remaining] == ["response.cancelled"]
