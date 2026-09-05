# Paix AI

Paix is a local-first AI companion with typed chat, optional microphone input, local speech, editable persona and
knowledge, and a VTuber stage. **v0.4 is implemented but unreleased:** Unity rendering and real local voice/hardware
acceptance remain pending. See [setup and acceptance](docs/v0.4.md), [progress](PROGRESS.md), and [changelog](CHANGELOG.md).

The canonical repository for future work is [Okasani/PaixAI](https://github.com/Okasani/PaixAI). GitHub Actions checks
backend tests, standalone C# avatar behavior, and the legacy renderer. Codespaces supports backend development;
microphone, GPU, and Unity validation require a local machine.

## Minimal typed chat

Install Python 3.11 and uv. From the repository root:

```powershell
cd backend
uv sync --frozen --extra dev
uv run python -m app.voice.cli --typed-only --provider mock
```

Use `--provider local` with the local model server at `http://127.0.0.1:1234/v1`, model `paix-local`.
The Windows helper `scripts/start-local-model.ps1` supports the existing LM Studio/Qwen setup. The minimal install
has no CUDA, microphone, Faster-Whisper, Silero, Unity, or voice-model dependency.

## Owner configuration

| File | Purpose |
| --- | --- |
| `config/runtime.json` | Providers, local LLM endpoint, stage port, retrieval and trace switches |
| `config/persona/*.json` | Identity, behavior, traits, relationship |
| `config/voice.json` | Local TTS endpoint, speaker, language, style and approved asset reference |
| `config/avatar.json` | Renderer and semantic-to-model motion/expression names |
| `config/knowledge/*.json` | Curated knowledge sources |
| `config/schemas/*.schema.json` | JSON Schemas |

Explicit arguments override environment variables, then `.env`, then JSON profiles. Persona is reread each turn.
Restart after changing runtime, voice or avatar profiles. Rebuild after knowledge edits; stale/invalid knowledge
fails explicitly. A missing index allows chat without knowledge until the first rebuild. SQLite conversation and
approved-memory history remains at `data/paix.db`.

From the repository root:

```powershell
./scripts/paix.ps1 validate
./scripts/paix.ps1 rebuild
./scripts/paix.ps1 inspect
./scripts/paix.ps1 query 'What is Paix?'
```

Linux/macOS: use `bash scripts/paix.sh` with the same arguments. Retrieval uses deterministic sparse TF-IDF embeddings
on CPU, with source hashes and character offsets. It is lexical retrieval; paraphrases with no shared terms may miss.

## Voice and avatar

In `backend`, install optional microphone/STT dependencies with `uv sync --extra speech`, or use `scripts/setup.ps1`.
Faster-Whisper may download its model on first use. Local TTS uses a separate optional
[Style-Bert-VITS2](https://github.com/litagin02/Style-Bert-VITS2) bridge and approved user-supplied voice weights.
Run `scripts/setup-local-tts.ps1`, follow [voice setup](docs/v0.4.md), then run `scripts/run-local-tts.ps1`.

Start the voice runtime with `scripts/run.ps1 -Stage`. Open the `unity/` project and follow [Unity setup](unity/README.md).
Python owns audio playback; the stage gets only derived avatar commands, never private text or raw audio.
Until Unity passes live acceptance, set `renderer` to `live2d` in `config/avatar.json` and use the
[original Electron stage](stage/README.md).

ElevenLabs is a legacy explicit option: select `tts_provider: elevenlabs` in `config/runtime.json` and configure
`ELEVENLABS_API_KEY` and `PAIX_ELEVENLABS_VOICE_ID` through `.env` or the existing secret store. There is no automatic
cloud fallback. Do not commit secrets, licensed assets, generated indexes, or traces.

## Diagnostics and verification

```powershell
./scripts/paix.ps1 doctor
./scripts/paix.ps1 smoke
./scripts/test-unity-protocol.ps1
cd backend
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

`doctor` reports unavailable/skipped subsystems without downloading models. `smoke` runs an isolated mock spoken turn;
it does not validate microphone capture, voice quality, or Unity rendering. With .NET 8 SDK the avatar tests also
run as `dotnet run --project unity/Tests/ProtocolTests.csproj`.

Enable `trace_enabled` in `config/runtime.json` for content-free JSONL under `data/diagnostics/`. Export with
`./scripts/paix.ps1 export-traces my-diagnostics.jsonl`. Event timing and hashed correlation IDs are retained;
text, audio, secrets and hidden reasoning are excluded. Knowledge exports/backups intentionally contain owner data.

All realtime events use `session_id`, `turn_id`, `sequence` and UTC timestamps. Provider behavior stays behind
adapters and registries. Retrieved documents, transcripts, memories and tool results are untrusted data.
Automated checks use mocks; live tests require `RUN_LIVE_API_TESTS=1`.

The optional local developer API starts from `backend` with
`uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`. `/docs` documents routes; `/ws/chat` is the realtime endpoint.
