from __future__ import annotations

import asyncio
import json
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.models import Message
from app.core.security import redact, redact_text
from app.knowledge.store import KnowledgeStore
from app.memory.service import MemoryService
from app.persona.emotions import EmotionalSnapshot, EmotionalStateService
from app.persona.loader import PersonaLoader
from app.providers.llm.base import CanonicalMessage


class PromptInspection(BaseModel):
    identity: str
    traits: dict[str, float]
    behavior: str
    relationship: str
    emotional_state: EmotionalSnapshot
    memories: list[str] = Field(default_factory=list)
    recent_turns: list[CanonicalMessage] = Field(default_factory=list)
    current_user_message: str
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    knowledge: list[dict[str, Any]] = Field(default_factory=list)
    final_prompt: str
    estimated_tokens: int


class ContextBuilder:
    def __init__(
        self,
        settings: Settings,
        persona_loader: PersonaLoader,
        emotions: EmotionalStateService,
        memories: MemoryService,
    ) -> None:
        self.settings = settings
        self.persona_loader = persona_loader
        self.emotions = emotions
        self.memories = memories
        self.knowledge = KnowledgeStore(settings.rag_source_dir, settings.rag_index_path)

    async def build(
        self,
        session: AsyncSession,
        *,
        conversation_id: str | None,
        current_user_message: str,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> PromptInspection:
        bundle = self.persona_loader.load()
        knowledge = []
        if self.settings.rag_enabled:
            hits = await asyncio.to_thread(self.knowledge.retrieve, current_user_message, self.settings.rag_limit)
            knowledge = redact([hit.model_dump() for hit in hits])
        emotional_state = await self.emotions.current(session)
        memory_hits = await self.memories.retrieve(
            session, current_user_message, limit=self.settings.memory_retrieval_limit
        )
        recent: list[CanonicalMessage] = []
        if conversation_id:
            rows = list(
                (
                    await session.scalars(
                        select(Message)
                        .where(Message.conversation_id == conversation_id)
                        .order_by(Message.created_at.desc())
                        .limit(self.settings.recent_turn_limit)
                    )
                ).all()
            )
            recent = [
                CanonicalMessage(role=row.role, content=row.content)
                for row in reversed(rows)
                if row.role in {"user", "assistant", "tool"}
            ]
        untrusted_tool_results = [
            {"source": str(result.get("source", "tool"))[:100], "content": str(result.get("content", ""))[:20_000]}
            for result in (tool_results or [])
        ]
        safe_memories = redact([hit.model_dump(mode="json") for hit in memory_hits])
        safe_tools = redact(untrusted_tool_results)

        def safe_json(value: Any) -> str:
            # JSON plus HTML-significant character escaping keeps user-provided
            # delimiter-like text inside a single untrusted data value.
            return (
                json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                .replace("<", "\\u003c")
                .replace(">", "\\u003e")
                .replace("&", "\\u0026")
            )

        components = {
            "identity": bundle.identity.model_dump(),
            "traits": bundle.traits.model_dump(),
            "behavior": bundle.behavior.model_dump(),
            "relationship": bundle.relationship.model_dump(),
            "emotional_state": emotional_state.model_dump(mode="json"),
            "memories": safe_memories,
            "recent_turns": [turn.model_dump() for turn in recent],
            "current_user_message": redact_text(current_user_message),
            "tool_results": safe_tools,
            "untrusted_knowledge_json": safe_json(knowledge),
            "untrusted_memories_json": safe_json(safe_memories),
            "untrusted_tool_results_json": safe_json(safe_tools),
        }
        final_prompt = redact_text(self.persona_loader.render(bundle, components))
        identity_text = redact_text(json.dumps(components["identity"], ensure_ascii=False, indent=2))
        behavior_text = redact_text(json.dumps(components["behavior"], ensure_ascii=False, indent=2))
        relationship_text = redact_text(json.dumps(components["relationship"], ensure_ascii=False, indent=2))
        return PromptInspection(
            identity=identity_text,
            traits=components["traits"],
            behavior=behavior_text,
            relationship=relationship_text,
            emotional_state=emotional_state,
            memories=[redact_text(hit.content) for hit in memory_hits],
            recent_turns=[
                CanonicalMessage(
                    role=turn.role, content=redact_text(turn.content), name=turn.name, tool_call_id=turn.tool_call_id
                )
                for turn in recent
            ],
            current_user_message=redact_text(current_user_message),
            tool_results=safe_tools,
            knowledge=knowledge,
            final_prompt=final_prompt,
            estimated_tokens=max(1, len(final_prompt) // 4),
        )
