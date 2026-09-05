from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import shutil
from pathlib import Path

from app.core.config import PROJECT_ROOT, Settings
from app.core.json_config import AvatarProfile, ConfigFileError, RuntimeProfile, VoiceProfile, atomic_json, read_json
from app.diagnostics.trace import export_traces
from app.knowledge.store import KnowledgeDocument, KnowledgeStore
from app.persona.loader import BehaviorConfig, IdentityConfig, PersonaLoader, RelationshipConfig, TraitsConfig


def validate() -> dict:
    settings = Settings()
    PersonaLoader(settings).load()
    read_json(PROJECT_ROOT / "config" / "avatar.json", AvatarProfile)
    store = KnowledgeStore(settings.rag_source_dir, settings.rag_index_path)
    documents = store.documents()
    return {"configuration": "pass", "knowledge_documents": len(documents)}


def schemas() -> None:
    models = {
        "runtime": RuntimeProfile,
        "voice": VoiceProfile,
        "avatar": AvatarProfile,
        "knowledge": KnowledgeDocument,
        "identity": IdentityConfig,
        "traits": TraitsConfig,
        "behavior": BehaviorConfig,
        "relationship": RelationshipConfig,
    }
    for name, model in models.items():
        atomic_json(PROJECT_ROOT / "config" / "schemas" / f"{name}.schema.json", model.model_json_schema())


async def doctor(settings: Settings, mock: bool = False) -> dict:
    from app.core.runtime import build_runtime

    result = {"configuration": "pass", "persona": "pass"}
    validate()
    if mock:
        settings = settings.model_copy(update={"default_provider": "mock", "tts_provider": "mock"})
    runtime = build_runtime(settings)
    provider = runtime.providers.get(settings.default_provider)
    # Health checks contact only the selected local providers. Cloud is always opt-in elsewhere.
    for name, adapter in (("llm", provider), ("tts", runtime.tts)):
        if adapter.provider_id not in {"local", "style_bert_vits2", "mock"}:
            result[name] = "skipped"
        else:
            health = await adapter.health_check()
            result[name] = "pass" if health.status == "ok" else "unavailable"
    for name, module in (("stt_dependency", "faster_whisper"), ("audio_dependency", "sounddevice")):
        result[name] = "pass" if importlib.util.find_spec(module) else "unavailable"
    result["stt_model"] = "skipped"  # Never trigger a model download in diagnostics.
    result["gpu_tools"] = "pass" if shutil.which("nvidia-smi") else "unavailable"
    result["rag"] = KnowledgeStore(settings.rag_source_dir, settings.rag_index_path).status()
    if mock:
        result["avatar_transport"] = "skipped"
        result["audio_devices"] = "skipped"
    else:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(settings.stage_host, settings.stage_port), 2)
            writer.close()
            await writer.wait_closed()
            result["avatar_transport"] = "pass"
        except (OSError, TimeoutError):
            result["avatar_transport"] = "unavailable"
        try:
            from app.voice.audio import list_audio_devices

            devices = await asyncio.to_thread(list_audio_devices)
            result["audio_devices"] = "pass" if devices else "unavailable"
        except (ImportError, RuntimeError, OSError):
            result["audio_devices"] = "unavailable"
    result["unity_renderer"] = "skipped"  # A listening socket is not proof that Unity rendered a model.
    return result


async def smoke() -> dict:
    """One deterministic typed-to-spoken turn through the real orchestrator, with mock providers."""
    import tempfile
    from unittest.mock import patch

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.avatar.live2d import Live2DAvatarAdapter
    from app.core.db import Base
    from app.core.runtime import build_runtime

    with tempfile.TemporaryDirectory(prefix="paix-smoke-") as directory:
        engine = create_async_engine(f"sqlite+aiosqlite:///{Path(directory).as_posix()}/smoke.db")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        events = []

        class Sink:
            async def send_json(self, event):
                events.append(event)

        settings = Settings(default_provider="mock", tts_provider="mock", trace_enabled=False, rag_enabled=False)
        runtime = build_runtime(settings)
        try:
            with patch(
                "app.orchestration.service.AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False)
            ):
                connection = await runtime.orchestrator.connect(Sink(), "smoke")
                await runtime.orchestrator.start_turn(connection, "turn", {"text": "Hello", "voice_enabled": True})
                await asyncio.wait_for(connection.active.task, 10)
                await runtime.orchestrator.disconnect(connection)
                await asyncio.sleep(0.05)
            types = {event["type"] for event in events}
            avatar = Live2DAvatarAdapter()
            commands = [avatar.transform(event) for event in events]
            passed = {"response.completed", "tts.audio"}.issubset(types) and not types.intersection(
                {"tts.error", "provider.error"}
            )
            return {
                "mock_spoken_turn": "pass" if passed else "fail",
                "avatar_mapping": "pass" if any(commands) else "fail",
                "microphone": "skipped",
                "live_tts": "skipped",
                "unity_render": "skipped",
            }
        finally:
            await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Paix local configuration, knowledge, and diagnostics")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "schemas", "rebuild", "inspect", "smoke"):
        sub.add_parser(name)
    check = sub.add_parser("doctor")
    check.add_argument("--mock", action="store_true")
    query = sub.add_parser("query")
    query.add_argument("text")
    importer = sub.add_parser("import")
    importer.add_argument("path", type=Path)
    importer.add_argument("--id", required=True)
    importer.add_argument("--title", required=True)
    for command in ("export", "backup", "export-traces"):
        sub.add_parser(command).add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        settings = Settings()
        store = KnowledgeStore(settings.rag_source_dir, settings.rag_index_path)
        if args.command == "validate":
            result = validate()
        elif args.command == "schemas":
            schemas()
            result = {"schemas": "pass"}
        elif args.command == "rebuild":
            index = store.rebuild()
            result = {"chunks": len(index.chunks), "fingerprint": index.fingerprint}
        elif args.command == "inspect":
            index = store.load()
            result = {
                "status": store.status(),
                "chunks": len(index.chunks),
                "embedding": index.embedding,
                "fingerprint": index.fingerprint,
            }
        elif args.command == "query":
            result = {"results": [hit.model_dump() for hit in store.retrieve(args.text, settings.rag_limit)]}
        elif args.command == "import":
            result = {"imported": store.import_document(args.path, args.id, args.title).name, "rebuild_required": True}
        elif args.command in {"export", "backup"}:
            # Explicit owner export contains source content, unlike a diagnostic bundle.
            if args.destination.exists():
                raise ValueError("Destination exists; choose a new file")
            result = {"knowledge": [doc.model_dump() for _, doc in store.documents()]}
            if args.command == "backup":
                result["persona"] = PersonaLoader(settings).raw_files()
                result["profiles"] = {
                    name: json.loads((PROJECT_ROOT / "config" / f"{name}.json").read_text())
                    for name in ("runtime", "voice", "avatar")
                }
            atomic_json(args.destination, result)
            result = {"export": "pass", "contains_private_source_content": True}
        elif args.command == "export-traces":
            result = {"records": export_traces(settings.trace_path, args.destination)}
        elif args.command == "smoke":
            result = asyncio.run(smoke())
        else:
            result = asyncio.run(doctor(settings, args.mock))
        print(json.dumps(result, indent=2))
        return (
            1
            if any(value in ("fail", "unavailable", "stale") for value in result.values() if isinstance(value, str))
            else 0
        )
    except ConfigFileError as exc:
        print(json.dumps({"status": "fail", "message": str(exc)}))
        return 1
    except (ValueError, OSError, KeyError):
        # CLI errors do not dump arbitrary source data or provider responses.
        print(
            json.dumps(
                {
                    "status": "fail",
                    "code": "validation_or_runtime_error",
                    "message": "Validate configuration and source JSON; check local subsystem setup.",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
