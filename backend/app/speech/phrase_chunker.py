from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator


class PhraseChunkerConfig(BaseModel):
    first_min_chars: int = Field(default=36, ge=12, le=300)
    min_chars: int = Field(default=64, ge=12, le=500)
    max_chars: int = Field(default=180, ge=40, le=1000)

    @model_validator(mode="after")
    def valid_thresholds(self) -> PhraseChunkerConfig:
        if self.first_min_chars > self.max_chars or self.min_chars > self.max_chars:
            raise ValueError("minimum phrase thresholds cannot exceed max_chars")
        return self


class PhraseChunker:
    """Incrementally extracts natural phrases without changing their text."""

    _sentence = re.compile(r"[.!?](?:[\"'”’)]*)\s+")
    _clause = re.compile(r"[,;:](?:[\"'”’)]*)\s+|\s+[—–-]\s+")

    def __init__(self, config: PhraseChunkerConfig | None = None) -> None:
        self.config = config or PhraseChunkerConfig()
        self._buffer = ""
        self._emitted = 0

    @property
    def buffered_text(self) -> str:
        return self._buffer

    def _boundary(self, minimum: int) -> int | None:
        for pattern in (self._sentence, self._clause):
            for match in pattern.finditer(self._buffer):
                if minimum <= match.end() <= self.config.max_chars:
                    return match.end()
        if len(self._buffer) >= self.config.max_chars:
            window = self._buffer[: self.config.max_chars]
            whitespace = [match.end() for match in re.finditer(r"\s+", window) if match.end() >= minimum]
            return whitespace[-1] if whitespace else self.config.max_chars
        return None

    def feed(self, text: str) -> list[str]:
        if not text:
            return []
        self._buffer += text
        output: list[str] = []
        while self._buffer:
            minimum = self.config.first_min_chars if self._emitted == 0 else self.config.min_chars
            boundary = self._boundary(minimum)
            if boundary is None:
                break
            output.append(self._buffer[:boundary])
            self._buffer = self._buffer[boundary:]
            self._emitted += 1
        return output

    def flush(self) -> list[str]:
        if not self._buffer:
            return []
        remainder = self._buffer
        self._buffer = ""
        self._emitted += 1
        return [remainder]

    def reset(self) -> None:
        self._buffer = ""
        self._emitted = 0
