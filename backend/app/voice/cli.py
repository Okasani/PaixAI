from __future__ import annotations

import argparse
import asyncio
import base64
import sys
import uuid
from typing import Any

import httpx

from app.avatar.transport import AvatarEventFanout, Live2DStageServer
from app.core.config import get_settings
from app.core.db import init_db
from app.core.runtime import build_runtime
from app.voice.audio import (
    AudioDependencyError,
    PCMPlayer,
    list_audio_devices,
    record_push_to_talk,
    record_until_silence,
)


class QueueEventSink:
    def __init__(self) -> None:
        self.events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def send_json(self, event: dict[str, Any]) -> None:
        await self.events.put(event)


class TerminalEvents:
    def __init__(self, sink: QueueEventSink, player: PCMPlayer | None) -> None:
        self.sink = sink
        self.player = player
        self.turn_done: dict[str, asyncio.Event] = {}
        self.response_started: set[str] = set()
        self.accept_audio = True

    def prepare_turn(self, turn_id: str) -> asyncio.Event:
        done = asyncio.Event()
        self.turn_done[turn_id] = done
        self.accept_audio = True
        return done

    async def stop_audio(self) -> None:
        self.accept_audio = False
        if self.player is not None:
            await asyncio.to_thread(self.player.cancel)

    async def run(self) -> None:
        while True:
            event = await self.sink.events.get()
            if event is None:
                return
            await self.handle(event)

    async def handle(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", ""))
        turn_id = str(event.get("turn_id", ""))
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}

        if event_type == "turn.state":
            state = str(payload.get("state", ""))
            if state in {"listening", "transcribing", "thinking", "speaking"}:
                print(f"[{state}]", flush=True)
            if state in {"idle", "error"}:
                done = self.turn_done.get(turn_id)
                if done is not None:
                    done.set()
                if state == "error":
                    print("[turn failed]", flush=True)
        elif event_type == "stt.final":
            transcript = str(payload.get("text", "")).strip()
            print(f"You: {transcript}" if transcript else "[no speech detected]", flush=True)
        elif event_type == "response.started":
            self.response_started.add(turn_id)
            print("Paix: ", end="", flush=True)
        elif event_type == "text.delta":
            if turn_id not in self.response_started:
                self.response_started.add(turn_id)
                print("Paix: ", end="", flush=True)
            print(str(payload.get("text", "")), end="", flush=True)
        elif event_type == "response.completed":
            print(flush=True)
        elif event_type == "tts.audio" and self.player is not None and self.accept_audio:
            encoded = payload.get("audio_base64") or payload.get("base64")
            if isinstance(encoded, str) and encoded:
                audio = base64.b64decode(encoded, validate=True)
                try:
                    await asyncio.to_thread(self.player.write, audio, int(payload.get("sample_rate", 24_000)))
                except Exception as exc:
                    await self.stop_audio()
                    print(f"[audio.error] Output device failed: {type(exc).__name__}: {str(exc)[:300]}")
        elif event_type == "audio.cancelled" and self.player is not None:
            await self.stop_audio()
        elif event_type in {"tts.skipped", "tts.error", "stt.error", "provider.error", "websocket.error"}:
            message = str(payload.get("message") or payload.get("reason") or event_type)
            print(f"[{event_type}] {message}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Voice-first local Paix runtime")
    parser.add_argument("--provider", help="LLM provider ID; defaults to the configured provider")
    parser.add_argument("--model", help="Provider model ID")
    parser.add_argument("--voice-id", help="TTS provider voice ID")
    parser.add_argument("--conversation-id", default="voice-primary", help="Persistent SQLite conversation ID")
    parser.add_argument("--input-device", help="sounddevice input device name or numeric ID")
    parser.add_argument("--output-device", help="sounddevice output device name or numeric ID")
    parser.add_argument("--typed-only", action="store_true", help="Disable microphone and audio playback")
    parser.add_argument("--push-to-talk", action="store_true", help="Require Enter to start and stop recording")
    parser.add_argument("--no-tts", action="store_true", help="Use microphone input without spoken responses")
    parser.add_argument("--list-devices", action="store_true", help="List audio devices and exit")
    parser.add_argument("--list-voices", action="store_true", help="List available TTS provider voices and exit")
    parser.add_argument("--stage", action="store_true", help="Publish sanitized avatar events to the Live2D stage")
    parser.add_argument("--stage-port", type=int, help="Override the loopback Live2D stage WebSocket port")
    return parser


def _device(value: str | None) -> str | int | None:
    if value is None:
        return None
    return int(value) if value.isdigit() else value


async def _choose_voice(runtime: Any, requested: str | None, *, list_only: bool = False) -> str | None:
    voice_id = requested or runtime.settings.tts_voice_id
    if voice_id and not list_only:
        return voice_id
    if not runtime.tts.configured():
        if list_only:
            print("Selected TTS provider is not configured.")
        return None
    try:
        voices = await runtime.tts.list_voices()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {401, 403}:
            print(
                f"TTS provider rejected the configured credential (HTTP {status}). "
                "Replace the key and ensure it has voice-read and text-to-speech access."
            )
        else:
            print(f"Unable to list TTS provider voices: HTTP {status}")
        return None
    except Exception as exc:
        print(f"Unable to list TTS provider voices: {type(exc).__name__}: {str(exc)[:300]}")
        return None
    if not voices:
        print("No TTS provider voices were returned.")
        return None
    for index, voice in enumerate(voices, start=1):
        print(f"{index:>2}. {voice.name} ({voice.voice_id})")
    if list_only:
        return None
    choice = (await asyncio.to_thread(input, "Select a voice number: ")).strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(voices):
        print("No valid voice selected; responses will be printed without TTS.")
        return None
    return voices[int(choice) - 1].voice_id


async def _run(args: argparse.Namespace) -> int:
    if args.list_devices:
        try:
            print(list_audio_devices())
        except AudioDependencyError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0

    await init_db()
    settings = get_settings()
    runtime = build_runtime(settings)
    provider_id = args.provider or settings.default_provider
    try:
        provider = runtime.providers.get(provider_id)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not provider.configured():
        print(f"Provider '{provider_id}' is not configured.", file=sys.stderr)
        return 2

    if args.list_voices:
        await _choose_voice(runtime, args.voice_id, list_only=True)
        return 0
    voice_id = None if args.no_tts or args.typed_only else await _choose_voice(runtime, args.voice_id)

    player: PCMPlayer | None = None
    if not args.typed_only and not args.no_tts and voice_id:
        player = PCMPlayer(_device(args.output_device))
    terminal_sink = QueueEventSink()
    terminal = TerminalEvents(terminal_sink, player)
    stage_server: Live2DStageServer | None = None
    sink: QueueEventSink | AvatarEventFanout = terminal_sink
    if args.stage:
        stage_port = args.stage_port or settings.stage_port
        if not 1024 <= stage_port <= 65535:
            print("Live2D stage port must be between 1024 and 65535.", file=sys.stderr)
            return 2
        stage_server = Live2DStageServer(host=settings.stage_host, port=stage_port)
        try:
            await stage_server.start()
        except OSError as exc:
            print(f"Unable to start Live2D stage stream: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
            return 2
        sink = AvatarEventFanout(terminal_sink, runtime.avatar_registry.get(settings.avatar_renderer), stage_server)
    session_id = f"voice-{uuid.uuid4()}"
    connection = await runtime.orchestrator.connect(sink, session_id)
    event_task = asyncio.create_task(terminal.run())

    print("Paix voice runtime")
    print(f"Provider: {provider_id} | Conversation: {args.conversation_id}")
    if stage_server is not None:
        print(f"Live2D stage events: {stage_server.url} (derived avatar commands only)")
    hands_free = not args.typed_only and not args.push_to_talk
    if args.typed_only:
        print("Typed-only mode. Enter a message, or /quit to exit.")
    elif args.push_to_talk:
        print("Push-to-talk mode. Press Enter to record, type /text for text, or /quit.")
    else:
        print("Hands-free mode. Speak when listening appears; pause naturally to submit. Press Ctrl+C to stop.")
        if voice_id is None or args.no_tts:
            print("Spoken output is disabled; responses will still appear in this terminal.")

    try:
        while True:
            command = "" if hands_free else (await asyncio.to_thread(input, "\n> ")).strip()
            if command.casefold() in {"/quit", "/exit", "quit", "exit"}:
                break
            if command == "/devices":
                try:
                    print(list_audio_devices())
                except AudioDependencyError as exc:
                    print(str(exc))
                continue

            source = "typed"
            text = command
            turn_id = str(uuid.uuid4())
            done = terminal.prepare_turn(turn_id)
            payload: dict[str, Any] = {
                "provider_id": provider_id,
                "conversation_id": args.conversation_id,
                "voice_enabled": not args.no_tts and voice_id is not None,
                "voice_id": voice_id,
                "output_format": "pcm_24000",
            }
            if args.model:
                payload["model_id"] = args.model

            if not args.typed_only and command != "/text" and not command:
                source = "microphone"
                await runtime.orchestrator.cancel_active(connection, "voice_barge_in")
                await connection.send("turn.state", turn_id, {"state": "listening"})
                try:
                    if hands_free:
                        wav = await record_until_silence(
                            device=_device(args.input_device),
                            vad_threshold=runtime.settings.vad_threshold,
                            silence_ms=runtime.settings.vad_silence_ms,
                            max_seconds=runtime.settings.max_utterance_seconds,
                        )
                    else:
                        wav = await asyncio.to_thread(
                            record_push_to_talk,
                            device=_device(args.input_device),
                        )
                except Exception as exc:
                    print(f"Microphone unavailable: {type(exc).__name__}: {str(exc)[:300]}")
                    terminal.turn_done.pop(turn_id, None)
                    continue
                await runtime.orchestrator.audio_chunk(
                    connection,
                    turn_id,
                    {"audio_base64": base64.b64encode(wav).decode("ascii")},
                )
                await runtime.orchestrator.audio_commit(
                    connection,
                    turn_id,
                    {**payload, "suffix": ".wav", "submit": True},
                )
            else:
                if command == "/text":
                    text = (await asyncio.to_thread(input, "Message: ")).strip()
                if not text:
                    terminal.turn_done.pop(turn_id, None)
                    continue
                await runtime.orchestrator.start_turn(connection, turn_id, {**payload, "text": text, "source": source})

            await done.wait()
            terminal.turn_done.pop(turn_id, None)
            terminal.response_started.discard(turn_id)
    except (KeyboardInterrupt, EOFError):
        print("\nStopping Paix...")
    finally:
        await terminal.stop_audio()
        await runtime.orchestrator.cancel_active(connection, "client_shutdown")
        await runtime.orchestrator.disconnect(connection)
        await terminal_sink.events.put(None)
        await event_task
        if player is not None:
            await asyncio.to_thread(player.close)
        if stage_server is not None:
            await stage_server.close()
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return asyncio.run(_run(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
