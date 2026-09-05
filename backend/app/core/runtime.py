from __future__ import annotations

from types import SimpleNamespace

from app.avatar.live2d import Live2DAvatarAdapter
from app.avatar.unity import UnityAvatarAdapter
from app.core.config import Settings, get_settings
from app.memory.service import MemoryService
from app.orchestration.service import RealtimeOrchestrator
from app.persona.context_builder import ContextBuilder
from app.persona.emotions import EmotionalStateService
from app.persona.loader import PersonaLoader
from app.providers.llm.registry import build_provider_registry
from app.providers.registry import ComponentRegistry
from app.providers.tts.registry import build_tts_registry
from app.speech.stt import FasterWhisperSTT
from app.tools.registry import build_tool_registry


def build_runtime(settings: Settings | None = None) -> SimpleNamespace:
    resolved = settings or get_settings()
    providers = build_provider_registry(resolved)
    persona_loader = PersonaLoader(resolved)
    emotions = EmotionalStateService()
    memories = MemoryService()
    context_builder = ContextBuilder(resolved, persona_loader, emotions, memories)
    tts_registry = build_tts_registry(resolved)
    tts = tts_registry.get(resolved.tts_provider)
    stt = FasterWhisperSTT(resolved)
    tools = build_tool_registry()
    stt_registry: ComponentRegistry = ComponentRegistry()
    stt_registry.register(stt)
    avatar_registry: ComponentRegistry = ComponentRegistry()
    avatar_registry.register(Live2DAvatarAdapter())
    avatar_registry.register(UnityAvatarAdapter())
    orchestrator = RealtimeOrchestrator(
        settings=resolved,
        providers=providers,
        context_builder=context_builder,
        emotions=emotions,
        memories=memories,
        tts=tts,
        stt=stt,
        tools=tools,
    )
    return SimpleNamespace(
        settings=resolved,
        providers=providers,
        persona_loader=persona_loader,
        emotions=emotions,
        memories=memories,
        context_builder=context_builder,
        tts=tts,
        stt=stt,
        tools=tools,
        stt_registry=stt_registry,
        tts_registry=tts_registry,
        avatar_registry=avatar_registry,
        orchestrator=orchestrator,
    )
