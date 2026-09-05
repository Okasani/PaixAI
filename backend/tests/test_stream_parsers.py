from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.providers.llm.anthropic_adapter import AnthropicProvider
from app.providers.llm.base import (
    CancellationToken,
    CanonicalLLMRequest,
    CanonicalMessage,
    CanonicalToolDefinition,
)
from app.providers.llm.openrouter import _sse_data


async def _lines(values: list[str]):
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_sse_parser_handles_comments_multiline_and_trailing_event() -> None:
    events = [
        event
        async for event in _sse_data(
            _lines(
                [
                    ": keepalive",
                    'data: {"first":',
                    "data: true}",
                    "",
                    "event: ignored",
                    "data: [DONE]",
                ]
            )
        )
    ]

    assert events == ['{"first":\ntrue}', "[DONE]"]


class _FakeAnthropicStream:
    def __init__(self) -> None:
        self.events = [
            SimpleNamespace(
                type="content_block_start",
                index=0,
                content_block=SimpleNamespace(type="tool_use", id="tool-1", name="get_current_time", input={}),
            ),
            SimpleNamespace(
                type="content_block_delta",
                index=0,
                delta=SimpleNamespace(type="input_json_delta", partial_json='{"timezone":'),
            ),
            SimpleNamespace(
                type="content_block_delta",
                index=0,
                delta=SimpleNamespace(type="input_json_delta", partial_json='"UTC"}'),
            ),
            SimpleNamespace(type="content_block_stop", index=0),
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for event in self.events:
            yield event

    async def get_final_message(self):
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=12, output_tokens=4),
            stop_reason="tool_use",
            model="claude-test",
        )


class _FakeAnthropicClient:
    def __init__(self) -> None:
        self.messages = self

    def stream(self, **kwargs):
        return _FakeAnthropicStream()


@pytest.mark.asyncio
async def test_anthropic_accumulates_streamed_tool_arguments() -> None:
    provider = AnthropicProvider(Settings())
    provider.configured = lambda: True  # type: ignore[method-assign]
    provider._client = lambda: _FakeAnthropicClient()  # type: ignore[method-assign]
    request = CanonicalLLMRequest(
        model="claude-test",
        system_prompt="system",
        messages=[CanonicalMessage(role="user", content="What time is it?")],
        tools=[
            CanonicalToolDefinition(
                name="get_current_time",
                description="Return the current time",
                input_schema={"type": "object"},
            )
        ],
    )

    events = [event async for event in provider.stream_response(request, CancellationToken())]
    tool_event = next(event for event in events if event.type == "tool.call")

    assert tool_event.payload == {
        "id": "tool-1",
        "name": "get_current_time",
        "arguments": '{"timezone":"UTC"}',
    }
    assert events[-1].type == "response.completed"
