from __future__ import annotations

from collections.abc import AsyncIterator


async def sse_data(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """Yield complete SSE data payloads, including multiline events."""
    data_lines: list[str] = []
    async for line in lines:
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if field != "data":
            continue
        if separator and value.startswith(" "):
            value = value[1:]
        data_lines.append(value)
    if data_lines:
        yield "\n".join(data_lines)
