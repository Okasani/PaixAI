from __future__ import annotations

import re
from datetime import UTC, datetime
from difflib import SequenceMatcher

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Memory, MemoryCandidate


class MemoryHit(BaseModel):
    id: str
    category: str
    content: str
    importance: float
    confidence: float
    reason: str
    score: float


def normalize_memory(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def terms(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9']+", value.casefold()) if len(word) > 2}


class MemoryService:
    async def retrieve(self, session: AsyncSession, query: str, limit: int = 8) -> list[MemoryHit]:
        memories = list(
            (
                await session.scalars(
                    select(Memory)
                    .where(Memory.status == "approved")
                    .order_by(Memory.importance.desc(), Memory.last_accessed_at.desc(), Memory.created_at.desc())
                    .limit(100)
                )
            ).all()
        )
        query_terms = terms(query)
        now = datetime.now(UTC)
        scored: list[tuple[float, Memory, str]] = []
        for memory in memories:
            overlap = len(query_terms & terms(memory.content)) / max(1, len(query_terms))
            score = 0.50 * overlap + 0.35 * memory.importance + 0.15 * memory.confidence
            reason = (
                f"keyword relevance {overlap:.2f}, importance {memory.importance:.2f}, "
                f"confidence {memory.confidence:.2f}"
            )
            scored.append((score, memory, reason))
        hits = sorted(scored, key=lambda item: item[0], reverse=True)[:limit]
        for _, memory, reason in hits:
            memory.last_accessed_at = now
            memory.retrieval_reason = reason
        if hits:
            await session.commit()
        return [
            MemoryHit(
                id=memory.id,
                category=memory.category,
                content=memory.content,
                importance=memory.importance,
                confidence=memory.confidence,
                reason=reason,
                score=round(score, 4),
            )
            for score, memory, reason in hits
        ]

    async def is_duplicate(self, session: AsyncSession, content: str, exclude_id: str | None = None) -> bool:
        normalized = normalize_memory(content)
        exact = await session.scalar(select(Memory).where(Memory.normalized_content == normalized))
        if exact is not None and exact.id != exclude_id:
            return True
        candidates = list((await session.scalars(select(Memory).limit(200))).all())
        return any(
            item.id != exclude_id and SequenceMatcher(None, normalized, item.normalized_content).ratio() >= 0.92
            for item in candidates
        )

    async def extract_candidate(self, session: AsyncSession, message_id: str, text: str) -> MemoryCandidate | None:
        patterns = [
            ("preference", r"\bI (?:really )?(?:like|love|prefer|enjoy)\b.+"),
            ("identity", r"\bmy (?:name|birthday|job|role|timezone) is\b.+"),
            ("project", r"\bI(?:'m| am) (?:building|working on|studying)\b.+"),
            ("preference", r"\bplease (?:always|remember)\b.+"),
        ]
        compact = re.sub(r"\s+", " ", text.strip())
        if len(compact) < 12 or len(compact) > 500:
            return None
        category = next((category for category, pattern in patterns if re.search(pattern, compact, re.I)), None)
        if category is None:
            return None
        existing = await session.scalar(
            select(MemoryCandidate).where(
                or_(MemoryCandidate.content == compact, MemoryCandidate.source_message_id == message_id)
            )
        )
        if existing:
            return existing
        candidate = MemoryCandidate(
            source_message_id=message_id,
            category=category,
            content=compact,
            confidence=0.62,
            status="pending",
            rationale="Rule-based durable-information signal; user review required",
        )
        session.add(candidate)
        if not await self.is_duplicate(session, compact):
            session.add(
                Memory(
                    category=category,
                    content=compact,
                    normalized_content=normalize_memory(compact),
                    importance=0.5,
                    confidence=0.62,
                    source_message_id=message_id,
                    status="pending",
                )
            )
        await session.commit()
        await session.refresh(candidate)
        return candidate
