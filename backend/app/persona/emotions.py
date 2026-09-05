from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import PersonaState

EMOTION_KEYS = (
    "warmth",
    "energy",
    "concern",
    "excitement",
    "playfulness",
    "confidence",
    "conversational_intimacy",
)
DEFAULT_BASELINES = {
    "warmth": 0.78,
    "energy": 0.55,
    "concern": 0.20,
    "excitement": 0.42,
    "playfulness": 0.48,
    "confidence": 0.72,
    "conversational_intimacy": 0.62,
}


class EmotionalValues(BaseModel):
    warmth: float = 0.78
    energy: float = 0.55
    concern: float = 0.20
    excitement: float = 0.42
    playfulness: float = 0.48
    confidence: float = 0.72
    conversational_intimacy: float = 0.62

    @field_validator("*", mode="after")
    @classmethod
    def bounded(cls, value: float) -> float:
        return min(1.0, max(0.0, value))


class EmotionalSnapshot(BaseModel):
    values: EmotionalValues
    baselines: EmotionalValues
    reason: str
    created_at: Any | None = None


class EmotionalStateService:
    decay_rate = 0.08
    max_turn_change = 0.08

    async def current(self, session: AsyncSession) -> EmotionalSnapshot:
        row = await session.scalar(
            select(PersonaState).where(PersonaState.is_current.is_(True)).order_by(PersonaState.id.desc())
        )
        if row is None:
            row = PersonaState(
                values_json=dict(DEFAULT_BASELINES),
                baselines_json=dict(DEFAULT_BASELINES),
                reason="Initialized at configured baselines",
                is_current=True,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return EmotionalSnapshot(
            values=EmotionalValues.model_validate(row.values_json),
            baselines=EmotionalValues.model_validate(row.baselines_json),
            reason=row.reason,
            created_at=row.created_at,
        )

    async def _persist(
        self, session: AsyncSession, values: dict[str, float], baselines: dict[str, float], reason: str
    ) -> EmotionalSnapshot:
        await session.execute(update(PersonaState).where(PersonaState.is_current.is_(True)).values(is_current=False))
        row = PersonaState(values_json=values, baselines_json=baselines, reason=reason, is_current=True)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return EmotionalSnapshot(
            values=EmotionalValues.model_validate(values),
            baselines=EmotionalValues.model_validate(baselines),
            reason=reason,
            created_at=row.created_at,
        )

    async def update_for_message(self, session: AsyncSession, message: str) -> EmotionalSnapshot:
        snapshot = await self.current(session)
        values = snapshot.values.model_dump()
        baselines = snapshot.baselines.model_dump()
        for key in EMOTION_KEYS:
            values[key] += (baselines[key] - values[key]) * self.decay_rate

        lowered = message.casefold()
        reasons: list[str] = []
        if any(word in lowered for word in ("sad", "hurt", "lonely", "upset", "failed", "discouraged")):
            values["concern"] += 0.08
            values["warmth"] += 0.04
            values["playfulness"] -= 0.05
            reasons.append("supportive response to discouragement")
        if any(word in lowered for word in ("great", "excited", "amazing", "wonderful", "success", "done!")):
            values["excitement"] += 0.07
            values["energy"] += 0.05
            reasons.append("shared positive momentum")
        if any(word in lowered for word in ("code", "debug", "technical", "architecture", "error", "test")):
            values["confidence"] += 0.04
            values["energy"] += 0.02
            reasons.append("focused technical collaboration")
        if any(word in lowered for word in ("joke", "funny", "play", "tease")):
            values["playfulness"] += 0.07
            reasons.append("playful conversational cue")
        if any(word in lowered for word in ("thank you", "thanks", "love", "trust")):
            values["warmth"] += 0.05
            values["conversational_intimacy"] += 0.04
            reasons.append("warm relational cue")
        bounded = {key: round(min(1.0, max(0.0, value)), 4) for key, value in values.items()}
        reason = "; ".join(reasons) if reasons else "gentle decay toward emotional baselines"
        return await self._persist(session, bounded, baselines, reason)

    async def adjust(
        self, session: AsyncSession, changes: dict[str, float], *, update_baselines: bool = False
    ) -> EmotionalSnapshot:
        unknown = set(changes) - set(EMOTION_KEYS)
        if unknown:
            raise ValueError(f"Unknown emotional values: {', '.join(sorted(unknown))}")
        snapshot = await self.current(session)
        values = snapshot.values.model_dump()
        baselines = snapshot.baselines.model_dump()
        for key, value in changes.items():
            if not 0 <= value <= 1:
                raise ValueError("Emotional values must be between 0 and 1")
            values[key] = round(value, 4)
            if update_baselines:
                baselines[key] = round(value, 4)
        return await self._persist(session, values, baselines, "manual emotional state adjustment")

    async def reset(self, session: AsyncSession) -> EmotionalSnapshot:
        snapshot = await self.current(session)
        baselines = snapshot.baselines.model_dump()
        return await self._persist(session, dict(baselines), baselines, "reset to emotional baselines")

    async def history(self, session: AsyncSession, limit: int = 100) -> list[EmotionalSnapshot]:
        rows = list((await session.scalars(select(PersonaState).order_by(PersonaState.id.desc()).limit(limit))).all())
        return [
            EmotionalSnapshot(
                values=EmotionalValues.model_validate(row.values_json),
                baselines=EmotionalValues.model_validate(row.baselines_json),
                reason=row.reason,
                created_at=row.created_at,
            )
            for row in reversed(rows)
        ]
