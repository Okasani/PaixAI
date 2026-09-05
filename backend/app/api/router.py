from __future__ import annotations

import base64
import json
import platform
import sys
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ConversationCreate,
    MemoryCreate,
    MemoryImport,
    MemoryPatch,
    SettingsPatch,
    ToolExecuteRequest,
    VoiceSampleRequest,
)
from app.core.db import get_db
from app.core.models import (
    ConfigurationVersion,
    Conversation,
    Memory,
    MemoryCandidate,
    Message,
    ProviderUsage,
)
from app.core.security import redact, redacted_json, secret_store
from app.memory.service import MemoryService, normalize_memory
from app.providers.tts.base import TTSProvider

api_router = APIRouter(prefix="/api")


def runtime(request: Request) -> Any:
    return request.app.state.runtime


def memory_wire(memory: Memory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "category": memory.category,
        "content": memory.content,
        "importance": memory.importance,
        "confidence": memory.confidence,
        "source_message_id": memory.source_message_id,
        "status": memory.status,
        "retrieval_reason": memory.retrieval_reason,
        "created_at": memory.created_at,
        "updated_at": memory.updated_at,
        "last_access_at": memory.last_accessed_at,
        "last_accessed_at": memory.last_accessed_at,
    }


def snapshot_wire(snapshot: Any) -> dict[str, Any]:
    return {
        **snapshot.values.model_dump(),
        "baselines": snapshot.baselines.model_dump(),
        "reason": snapshot.reason,
        "updated_at": snapshot.created_at,
        "timestamp": snapshot.created_at,
    }


@api_router.get("/health")
async def health(request: Request, database: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    state = runtime(request)
    started = time.perf_counter()
    try:
        await database.execute(text("SELECT 1"))
        database_status = "ok"
    except Exception:
        database_status = "unavailable"
    return {
        "status": "ok" if database_status == "ok" else "degraded",
        "name": state.settings.app_name,
        "version": state.settings.app_version,
        "database": database_status,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "providers": {
            provider.provider_id: {"configured": provider.configured()} for provider in state.providers.all()
        },
        "tts": {"configured": state.tts.configured()},
        "stt": state.stt.status(),
    }


@api_router.get("/providers")
async def providers(request: Request) -> list[dict[str, Any]]:
    state = runtime(request)
    output: list[dict[str, Any]] = []
    for provider in state.providers.all():
        manifest = provider.manifest.model_dump(mode="json")
        capabilities = manifest["capabilities"]
        capabilities["tools"] = capabilities.get("tool_calls", False)
        capabilities["usage"] = capabilities.get("usage_reporting", False)
        capabilities["reasoning"] = capabilities.get("reasoning_metadata", False)
        manifest["configured"] = provider.configured()
        output.append(manifest)
    return output


@api_router.get("/avatars")
async def avatars(request: Request) -> list[dict[str, Any]]:
    return [adapter.manifest.model_dump(mode="json") for adapter in runtime(request).avatar_registry.all()]


@api_router.get("/providers/{provider_id}/models")
async def provider_models(provider_id: str, request: Request) -> list[dict[str, Any]]:
    state = runtime(request)
    try:
        provider = state.providers.get(provider_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        return [model.model_dump(mode="json") for model in await provider.list_models()]
    except Exception as exc:
        raise HTTPException(503, f"Could not list {provider_id} models: {type(exc).__name__}") from exc


@api_router.post("/providers/{provider_id}/health")
async def provider_health(provider_id: str, request: Request) -> dict[str, Any]:
    state = runtime(request)
    try:
        provider = state.providers.get(provider_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    result = await provider.health_check()
    wire = result.model_dump(mode="json")
    wire.update({"id": provider_id, "name": provider.manifest.display_name})
    wire["status"] = {"ok": "healthy", "degraded": "degraded", "unavailable": "unavailable"}[result.status]
    return wire


@api_router.get("/settings")
async def get_runtime_settings(request: Request) -> dict[str, Any]:
    state = runtime(request)
    result = state.settings.safe_dict()
    result["provider_configuration"] = {
        provider.provider_id: provider.configured() for provider in state.providers.all()
    }
    return result


@api_router.patch("/settings")
async def patch_runtime_settings(patch: SettingsPatch, request: Request) -> dict[str, Any]:
    state = runtime(request)
    values = patch.model_dump(exclude_none=True, exclude={"session_secrets", "persistent_secrets"})
    for name, value in values.items():
        setattr(state.settings, name, value)
    for name, value in patch.session_secrets.items():
        secret_store.set(name, value.strip() if isinstance(value, str) else None)
    for name, value in patch.persistent_secrets.items():
        try:
            secret_store.set_persistent(name, value.strip() if isinstance(value, str) else None)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
    return await get_runtime_settings(request)


@api_router.get("/persona/inspect")
async def inspect_persona(
    request: Request,
    message: str = Query(default="", max_length=100_000),
    conversation_id: str | None = Query(default=None, max_length=64),
    database: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    state = runtime(request)
    inspection = await state.context_builder.build(
        database, conversation_id=conversation_id or None, current_user_message=message
    )
    return inspection.model_dump(mode="json")


@api_router.get("/persona/state")
async def persona_state(request: Request, database: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return snapshot_wire(await runtime(request).emotions.current(database))


@api_router.patch("/persona/state")
async def update_persona_state(
    changes: dict[str, Any], request: Request, database: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    state = runtime(request)
    update_baselines = bool(changes.pop("update_baselines", False))
    allowed = {key: float(value) for key, value in changes.items() if key not in {"reason", "updated_at", "baselines"}}
    try:
        snapshot = await state.emotions.adjust(database, allowed, update_baselines=update_baselines)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return snapshot_wire(snapshot)


@api_router.post("/persona/state/reset")
async def reset_persona_state(request: Request, database: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return snapshot_wire(await runtime(request).emotions.reset(database))


@api_router.get("/persona/state/history")
async def persona_state_history(
    request: Request, limit: int = Query(100, ge=1, le=1000), database: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    return [snapshot_wire(item) for item in await runtime(request).emotions.history(database, limit)]


@api_router.get("/persona/config")
async def persona_config(request: Request) -> dict[str, Any]:
    return runtime(request).persona_loader.raw_files()


@api_router.put("/persona/config/{section}")
async def update_persona_config(
    section: str, content: dict[str, Any], request: Request, database: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    state = runtime(request)
    try:
        validated = state.persona_loader.validate_update(section, content)
        current = state.persona_loader.raw_files()[section]
        latest = await database.scalar(
            select(func.max(ConfigurationVersion.version)).where(ConfigurationVersion.kind == f"persona:{section}")
        )
        database.add(
            ConfigurationVersion(
                kind=f"persona:{section}",
                version=int(latest or 0) + 1,
                content_json=current,
                note="Snapshot before persona editor update",
            )
        )
        await database.commit()
        path = state.persona_loader.safe_path(state.settings.persona_dir, section)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return {"section": section, "content": validated}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@api_router.get("/persona/versions")
async def persona_versions(database: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    rows = list(
        (await database.scalars(select(ConfigurationVersion).order_by(ConfigurationVersion.id.desc()).limit(200))).all()
    )
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "version": row.version,
            "content": row.content_json,
            "note": row.note,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@api_router.post("/persona/config/reset")
async def reset_persona_config(request: Request, database: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    state = runtime(request)
    try:
        current = state.persona_loader.raw_files()
        defaults = state.persona_loader.repository_defaults()
        for section, _content in defaults.items():
            latest = await database.scalar(
                select(func.max(ConfigurationVersion.version)).where(ConfigurationVersion.kind == f"persona:{section}")
            )
            database.add(
                ConfigurationVersion(
                    kind=f"persona:{section}",
                    version=int(latest or 0) + 1,
                    content_json=current[section],
                    note="Snapshot before repository-default reset",
                )
            )
        await database.commit()
        for section, content in defaults.items():
            path = state.persona_loader.safe_path(state.settings.persona_dir, section)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(content, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
        return state.persona_loader.raw_files()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@api_router.post("/persona/versions/{version_id}/restore")
async def restore_persona_version(
    version_id: int, request: Request, database: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    state = runtime(request)
    version = await database.get(ConfigurationVersion, version_id)
    if version is None or not version.kind.startswith("persona:"):
        raise HTTPException(404, "Persona version not found")
    section = version.kind.split(":", 1)[1]
    validated = state.persona_loader.validate_update(section, version.content_json)
    path = state.persona_loader.safe_path(state.settings.persona_dir, section)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return {"section": section, "content": validated, "restored_from": version_id}


@api_router.get("/conversations")
async def list_conversations(database: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    rows = list((await database.scalars(select(Conversation).order_by(Conversation.updated_at.desc()))).all())
    return [
        {
            "id": row.id,
            "title": row.title,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "archived": row.archived,
        }
        for row in rows
    ]


@api_router.post("/conversations")
async def create_conversation(body: ConversationCreate, database: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = Conversation(title=body.title)
    database.add(row)
    await database.commit()
    await database.refresh(row)
    return {"id": row.id, "title": row.title, "created_at": row.created_at, "updated_at": row.updated_at}


@api_router.get("/conversations/{conversation_id}/messages")
async def conversation_messages(conversation_id: str, database: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    exists = await database.get(Conversation, conversation_id)
    if exists is None:
        raise HTTPException(404, "Conversation not found")
    rows = list(
        (
            await database.scalars(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
            )
        ).all()
    )
    return [
        {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "turn_id": row.turn_id,
            "role": row.role,
            "content": row.content,
            "provider_id": row.provider_id,
            "model_id": row.model_id,
            "metadata": row.metadata_json,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@api_router.delete("/conversations/{conversation_id}", status_code=204, response_class=Response)
async def remove_conversation(conversation_id: str, database: AsyncSession = Depends(get_db)) -> Response:
    row = await database.get(Conversation, conversation_id)
    if row is None:
        raise HTTPException(404, "Conversation not found")
    await database.delete(row)
    await database.commit()
    return Response(status_code=204)


@api_router.get("/memories/export")
async def export_memories(database: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = list((await database.scalars(select(Memory).order_by(Memory.created_at))).all())
    return {"version": 1, "exported_at": datetime.now(UTC), "items": [memory_wire(row) for row in rows]}


@api_router.post("/memories/import")
async def import_memories(
    body: MemoryImport, request: Request, database: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    service: MemoryService = runtime(request).memories
    imported = 0
    skipped = 0
    for item in body.items:
        if await service.is_duplicate(database, item.content):
            skipped += 1
            continue
        database.add(
            Memory(
                category=item.category,
                content=item.content,
                normalized_content=normalize_memory(item.content),
                importance=item.importance,
                confidence=item.confidence,
                source_message_id=item.source_message_id,
                status=item.status,
            )
        )
        imported += 1
    await database.commit()
    return {"imported": imported, "skipped": skipped}


@api_router.get("/memories/candidates")
async def memory_candidates(database: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    rows = list(
        (await database.scalars(select(MemoryCandidate).order_by(MemoryCandidate.created_at.desc()).limit(500))).all()
    )
    return [
        {
            "id": row.id,
            "source_message_id": row.source_message_id,
            "category": row.category,
            "content": row.content,
            "rationale": row.rationale,
            "confidence": row.confidence,
            "status": row.status,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@api_router.get("/memories")
async def list_memories(
    search: str = Query(default="", max_length=500),
    category: str | None = Query(default=None, max_length=80),
    status: str | None = Query(default=None, max_length=24),
    database: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    query = select(Memory)
    if search:
        query = query.where(Memory.content.ilike(f"%{search}%"))
    if category:
        query = query.where(Memory.category == category)
    if status:
        query = query.where(Memory.status == status)
    rows = list((await database.scalars(query.order_by(Memory.created_at.desc()).limit(1000))).all())
    return [memory_wire(row) for row in rows]


@api_router.post("/memories", status_code=201)
async def create_memory(
    body: MemoryCreate, request: Request, database: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    if await runtime(request).memories.is_duplicate(database, body.content):
        raise HTTPException(409, "A duplicate or near-duplicate memory already exists")
    row = Memory(
        category=body.category,
        content=body.content,
        normalized_content=normalize_memory(body.content),
        importance=body.importance,
        confidence=body.confidence,
        source_message_id=body.source_message_id,
        status=body.status,
    )
    database.add(row)
    await database.commit()
    await database.refresh(row)
    return memory_wire(row)


@api_router.patch("/memories/{memory_id}")
async def update_memory(
    memory_id: str, patch: MemoryPatch, request: Request, database: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    row = await database.get(Memory, memory_id)
    if row is None:
        raise HTTPException(404, "Memory not found")
    changes = patch.model_dump(exclude_none=True)
    if "content" in changes:
        if await runtime(request).memories.is_duplicate(database, changes["content"], exclude_id=memory_id):
            raise HTTPException(409, "A duplicate or near-duplicate memory already exists")
        changes["normalized_content"] = normalize_memory(changes["content"])
    for name, value in changes.items():
        setattr(row, name, value)
    await database.commit()
    await database.refresh(row)
    return memory_wire(row)


@api_router.delete("/memories/{memory_id}", status_code=204, response_class=Response)
async def delete_memory(memory_id: str, database: AsyncSession = Depends(get_db)) -> Response:
    row = await database.get(Memory, memory_id)
    if row is None:
        raise HTTPException(404, "Memory not found")
    await database.delete(row)
    await database.commit()
    return Response(status_code=204)


@api_router.get("/tts/voices")
async def tts_voices(request: Request) -> dict[str, Any]:
    provider: TTSProvider = runtime(request).tts
    if not provider.configured():
        return {"voices": [], "configured": False}
    try:
        voices = await provider.list_voices()
    except Exception as exc:
        raise HTTPException(503, f"Could not refresh TTS voices: {type(exc).__name__}") from exc
    return {"voices": [voice.model_dump(mode="json") for voice in voices], "configured": True}


@api_router.get("/tts/models")
async def tts_models(request: Request) -> dict[str, Any]:
    try:
        models = await runtime(request).tts.list_models()
    except Exception as exc:
        raise HTTPException(503, f"Could not refresh TTS models: {type(exc).__name__}") from exc
    return {"items": models}


@api_router.post("/tts/health")
async def tts_health(request: Request) -> dict[str, Any]:
    return (await runtime(request).tts.health_check()).model_dump(mode="json")


@api_router.post("/tts/sample")
async def tts_sample(body: VoiceSampleRequest, request: Request) -> dict[str, Any]:
    try:
        audio, metrics = await runtime(request).tts.generate_sample(
            text=body.text,
            voice_id=body.voice_id,
            model_id=body.model_id,
            output_format=body.output_format,
            voice_settings=body.voice_settings,
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"TTS sample failed: {type(exc).__name__}") from exc
    actual_format = str(metrics.get("output_format", body.output_format))
    mime = "audio/pcm" if actual_format.startswith("pcm") else "audio/mpeg"
    return {"audio_base64": base64.b64encode(audio).decode("ascii"), "mime_type": mime, "metrics": metrics}


@api_router.get("/stt/status")
async def stt_status(request: Request) -> dict[str, Any]:
    return runtime(request).stt.status()


@api_router.post("/stt/transcribe")
async def stt_transcribe(
    request: Request,
    audio: UploadFile = File(...),
    model: str | None = Form(default=None),
    already_segmented: bool = Form(default=False),
) -> dict[str, Any]:
    state = runtime(request)
    content = await audio.read(state.settings.max_audio_bytes + 1)
    if len(content) > state.settings.max_audio_bytes:
        raise HTTPException(413, "Audio exceeds the configured upload limit")
    if not content:
        raise HTTPException(422, "Audio file is empty")
    suffix = ".webm" if "webm" in (audio.content_type or "") else ".wav"
    try:
        result = await state.stt.transcribe_bytes(
            content, suffix=suffix, model_name=model, already_segmented=already_segmented
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Transcription failed: {type(exc).__name__}") from exc
    return result.model_dump(mode="json")


@api_router.get("/tools")
async def tools(request: Request) -> list[dict[str, Any]]:
    return [tool.model_dump(mode="json") for tool in runtime(request).tools.manifests()]


@api_router.post("/tools/{tool_name}/execute")
async def execute_tool(tool_name: str, body: ToolExecuteRequest, request: Request) -> dict[str, Any]:
    try:
        result = await runtime(request).tools.execute(tool_name, body.arguments, confirmed=body.confirmed)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, TimeoutError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"tool": tool_name, "output": redact(result)}


@api_router.get("/usage")
async def usage(conversation_id: str | None = None, database: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    query = select(ProviderUsage)
    if conversation_id:
        query = query.where(ProviderUsage.conversation_id == conversation_id)
    rows = list((await database.scalars(query.order_by(ProviderUsage.created_at.desc()).limit(5000))).all())
    return {
        "input_tokens": sum(row.input_tokens for row in rows),
        "output_tokens": sum(row.output_tokens for row in rows),
        "tts_characters": sum(row.tts_characters for row in rows),
        "estimated_cost_usd": sum(row.estimated_cost_usd or 0 for row in rows),
        "turns": [
            {
                "turn_id": row.turn_id,
                "provider": row.provider_id,
                "model": row.model_id,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "tts_characters": row.tts_characters,
                "estimated_cost_usd": row.estimated_cost_usd,
                "created_at": row.created_at,
            }
            for row in rows
        ],
    }


@api_router.post("/bug-report")
async def bug_report(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    state = runtime(request)
    report = {
        "application": {"name": state.settings.app_name, "version": state.settings.app_version},
        "system": {"os": platform.platform(), "python": sys.version.split()[0]},
        "configuration": {
            "local_tts_selected": state.settings.tts_provider == "style_bert_vits2",
            "rag_enabled": state.settings.rag_enabled,
            "traces_enabled": state.settings.trace_enabled,
        },
        "diagnostics": {"submitted_content_excluded": True},
        "generated_at": datetime.now(UTC).isoformat(),
        "notice": "Submitted content, local paths, secrets, audio, and hidden reasoning are excluded.",
    }
    return {"report": redacted_json(report), "structured": redact(report)}
