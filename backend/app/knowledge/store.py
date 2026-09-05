from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field

from app.core.json_config import StrictConfig, atomic_json, read_json


class KnowledgeDocument(StrictConfig):
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1, max_length=100, pattern=r"^[\w.-]+$")
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200_000)
    source: str = Field(min_length=1, max_length=1000)


class Chunk(StrictConfig):
    id: str
    document_id: str
    title: str
    source: str
    source_file: str
    source_sha256: str
    start: int
    end: int
    content: str
    embedding: dict[str, float]


class Index(StrictConfig):
    schema_version: Literal[1] = 1
    embedding: Literal["local-token-tfidf-v1"] = "local-token-tfidf-v1"
    fingerprint: str
    idf: dict[str, float]
    chunks: list[Chunk]


class Retrieval(StrictConfig):
    chunk_id: str
    document_id: str
    source: str
    source_file: str
    source_sha256: str
    start: int
    end: int
    content: str
    score: float


def tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())[:50_000]


def embed(text: str, idf: dict[str, float]) -> dict[str, float]:
    # Sparse TF-IDF embeddings: deterministic, CPU-only, no model download or service.
    counts = Counter(tokens(text))
    vector = {word: (1 + math.log(count)) * idf[word] for word, count in counts.items() if word in idf}
    norm = math.sqrt(sum(value * value for value in vector.values())) or 1
    return {word: value / norm for word, value in sorted(vector.items())}


class KnowledgeStore:
    def __init__(self, source_dir: Path, index_path: Path) -> None:
        self.source_dir = source_dir
        self.index_path = index_path

    def documents(self) -> list[tuple[Path, KnowledgeDocument]]:
        result = []
        seen = set()
        root = self.source_dir.resolve()
        if not root.is_dir():
            raise ValueError("Knowledge source directory is unavailable")
        for path in sorted(root.glob("*.json")):
            if not path.resolve().is_relative_to(root):
                raise ValueError("Knowledge source escapes the source directory")
            document = read_json(path, KnowledgeDocument)
            if document.id in seen:
                raise ValueError(f"{path.name}: $.id: duplicate document identity")
            seen.add(document.id)
            result.append((path, document))
        return result

    @staticmethod
    def fingerprint(documents: list[tuple[Path, KnowledgeDocument]]) -> str:
        canonical = "\n".join(path.name + ":" + doc.model_dump_json() for path, doc in documents)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def rebuild(self) -> Index:
        documents = self.documents()  # Validate every source before touching the last good index.
        chunks: list[Chunk] = []
        for path, document in documents:
            digest = hashlib.sha256(document.content.encode()).hexdigest()
            for start in range(0, len(document.content), 700):
                end = min(start + 900, len(document.content))
                chunks.append(
                    Chunk(
                        id=f"{document.id}:{start}:{digest[:12]}",
                        document_id=document.id,
                        title=document.title,
                        source=document.source,
                        source_file=path.name,
                        source_sha256=digest,
                        start=start,
                        end=end,
                        content=document.content[start:end],
                        embedding={},
                    )
                )
                if end == len(document.content):
                    break
        frequencies: Counter[str] = Counter()
        for chunk in chunks:
            frequencies.update(set(tokens(chunk.content)))
        idf = {word: math.log((1 + len(chunks)) / (1 + count)) + 1 for word, count in sorted(frequencies.items())}
        for chunk in chunks:
            chunk.embedding = embed(chunk.content, idf)
        index = Index(fingerprint=self.fingerprint(documents), idf=idf, chunks=chunks)
        atomic_json(self.index_path, index.model_dump())
        return index

    def load(self) -> Index:
        # Indexes may be larger than individual source/config files.
        if self.index_path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("Knowledge index exceeds 32 MiB")
        try:
            return Index.model_validate_json(self.index_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise ValueError("Knowledge index is invalid; rebuild required") from None

    def status(self) -> str:
        if not self.index_path.is_file():
            return "unavailable"
        index = self.load()
        return "pass" if index.fingerprint == self.fingerprint(self.documents()) else "stale"

    def retrieve(self, query: str, limit: int = 4) -> list[Retrieval]:
        if not self.index_path.is_file():
            return []
        index = self.load()
        if index.fingerprint != self.fingerprint(self.documents()):
            raise ValueError("Knowledge sources changed; rebuild the index before retrieval")
        vector = embed(query, index.idf)
        scored = [
            (sum(value * chunk.embedding.get(word, 0) for word, value in vector.items()), chunk)
            for chunk in index.chunks
        ]
        return [
            Retrieval(
                chunk_id=chunk.id,
                score=round(score, 6),
                **chunk.model_dump(
                    include={"document_id", "source", "source_file", "source_sha256", "start", "end", "content"}
                ),
            )
            for score, chunk in sorted(scored, key=lambda pair: (-pair[0], pair[1].id))[:limit]
            if score > 0
        ]

    def import_document(self, path: Path, document_id: str, title: str) -> Path:
        if path.suffix.lower() not in {".txt", ".md"} or path.stat().st_size > 200_000:
            raise ValueError("Import supports UTF-8 .txt/.md documents up to 200 KB")
        document = KnowledgeDocument(
            id=document_id, title=title, content=path.read_text(encoding="utf-8"), source=path.name
        )
        destination = self.source_dir / f"{document.id}.json"
        if destination.exists() or any(doc.id == document.id for _, doc in self.documents()):
            raise ValueError("Document already exists; edit its source JSON explicitly")
        atomic_json(destination, document.model_dump())
        return destination
