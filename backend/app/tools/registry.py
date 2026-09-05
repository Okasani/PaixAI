from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

ToolHandler = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = True
    requires_confirmation: bool = False
    timeout_seconds: float = Field(default=5, gt=0, le=120)
    output_schema: dict[str, Any]


class RegisteredTool:
    def __init__(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        self.definition = definition
        self.handler = handler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool already registered: {definition.name}")
        if not definition.read_only and not definition.requires_confirmation:
            raise ValueError("Side-effecting tools require confirmation by default")
        self._tools[definition.name] = RegisteredTool(definition, handler)

    def manifests(self) -> list[ToolDefinition]:
        return [tool.definition for tool in self._tools.values()]

    async def execute(self, name: str, arguments: dict[str, Any], confirmed: bool = False) -> dict[str, Any]:
        try:
            tool = self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc
        if tool.definition.requires_confirmation and not confirmed:
            raise PermissionError(f"Tool '{name}' requires user confirmation")

        async def invoke() -> dict[str, Any]:
            result = tool.handler(arguments)
            if inspect.isawaitable(result):
                return await result
            return result

        return await asyncio.wait_for(invoke(), timeout=tool.definition.timeout_seconds)


def get_current_time(arguments: dict[str, Any]) -> dict[str, Any]:
    timezone = str(arguments.get("timezone", "UTC"))
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {timezone}") from exc
    now = datetime.now(zone)
    return {"timezone": timezone, "iso8601": now.isoformat(), "display": now.strftime("%A, %B %d, %Y at %H:%M:%S %Z")}


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="get_current_time",
            description="Return the current time in an IANA timezone. This is read-only.",
            input_schema={
                "type": "object",
                "properties": {"timezone": {"type": "string", "default": "UTC"}},
                "additionalProperties": False,
            },
            read_only=True,
            requires_confirmation=False,
            timeout_seconds=2,
            output_schema={
                "type": "object",
                "required": ["timezone", "iso8601", "display"],
                "properties": {
                    "timezone": {"type": "string"},
                    "iso8601": {"type": "string"},
                    "display": {"type": "string"},
                },
            },
        ),
        get_current_time,
    )
    return registry
