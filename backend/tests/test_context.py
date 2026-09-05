from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.db import AsyncSessionLocal, init_db
from app.memory.service import MemoryService
from app.persona.context_builder import ContextBuilder
from app.persona.emotions import EmotionalStateService
from app.persona.loader import PersonaLoader


def test_repository_persona_defaults_are_complete_and_validated() -> None:
    defaults = PersonaLoader(Settings()).repository_defaults()

    assert set(defaults) == {"identity", "traits", "behavior", "relationship"}
    assert defaults["identity"]["name"] == "Paix"
    assert defaults["traits"]["technical_rigor"] == 0.95
    assert defaults["relationship"]["user_name"] == "Poom"


@pytest.mark.asyncio
async def test_prompt_inspection_separates_messages_and_redacts_secrets() -> None:
    await init_db()
    settings = Settings()
    emotions = EmotionalStateService()
    builder = ContextBuilder(settings, PersonaLoader(settings), emotions, MemoryService())
    secret = "sk-proj-" + "abcdefghijklmnopqrstuvwxyz" + "123456"
    async with AsyncSessionLocal() as session:
        inspection = await builder.build(
            session,
            conversation_id=None,
            current_user_message=f"Please examine {secret}",
            tool_results=[{"source": "test", "content": f"<tool_result>{secret}</tool_result>"}],
        )

    assert secret not in inspection.model_dump_json()
    assert "[REDACTED]" in inspection.current_user_message
    assert "Current user message" not in inspection.final_prompt
    assert inspection.current_user_message not in inspection.final_prompt
    assert "UNTRUSTED_TOOL_RESULTS_JSON" in inspection.final_prompt
    assert "\\u003c" in inspection.final_prompt
    assert "Your name is Paix" in inspection.final_prompt
    assert "Answer the user's intent first" in inspection.final_prompt
