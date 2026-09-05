# Paix

Paix v0.3 is a local-model, voice-first AI companion runtime for Windows with an optional desktop Live2D presence.
It listens for speech continuously, detects sentence boundaries with Silero VAD, transcribes locally with
Faster-Whisper, runs the persona and memory pipeline through a local Qwen model, and streams spoken responses
through ElevenLabs.

There is no browser chat UI. The primary interface remains the VS Code integrated terminal or PowerShell. The
optional Electron stage is a renderer only: it receives sanitized avatar commands and never receives conversation
text, prompts, tool results, raw microphone audio, or raw TTS audio.

## What v0.3 Includes

- Hands-free 16 kHz mono microphone capture with automatic speech start/end detection.
- Local English Faster-Whisper transcription with explicit CUDA or CPU selection.
- Qwen3.5 4B Q4_K_M running locally through LM Studio as the default LLM, with no cloud fallback.
- Optional mock, OpenAI, Anthropic, and OpenRouter adapters for explicit developer tests only.
- Streaming ElevenLabs PCM speech output.
- Persistent conversations, memory, persona state, usage, and latency in SQLite.
- Voice-first terminal runtime with typed fallback.
- Optional loopback FastAPI/WebSocket API for development and future integrations.
- Optional Live2D Cubism 4 desktop stage with state animation, expression mapping, PCM-amplitude lip-sync,
  blinking, breathing, gaze, and subtle idle motion.
- An avatar adapter registry and a loopback-only, read-only stage stream using canonical Paix event envelopes.

## Setup on Windows

Requirements:

- Windows 10 or 11.
- VS Code.
- `uv`.
- LM Studio with its `lms` CLI installed.
- A working microphone and output device.
- FFmpeg for Faster-Whisper audio decoding.
- An NVIDIA GPU is optional; CPU transcription is supported.

From PowerShell:

```powershell
cd <path-to-this-project>
Set-ExecutionPolicy -Scope Process Bypass
./scripts/setup.ps1
```

Setup installs Python 3.11, development tools, and the optional voice dependencies. To install only the minimal typed runtime:

```powershell
./scripts/setup.ps1 -TypedOnly
```

Node.js and npm are not required for the core voice or typed runtime. They are required only for the optional
Live2D stage.

## Optional Live2D Stage

Paix does not redistribute the Live2D Cubism runtime or a character model. Obtain a licensed Cubism 4 model and
`live2dcubismcore.min.js` from the official Cubism SDK for Web, then install the stage:

```powershell
./scripts/setup-stage.ps1
./scripts/run-stage.ps1
```

On first launch, choose the model's `.model3.json` file and the Cubism Core JavaScript file. To persist paths and
map the semantic Paix motions/expressions to names supported by the model, copy `stage/config.example.json` to
`stage/config.json` and edit it. The local configuration is git-ignored.

Start the voice runtime in another terminal with avatar publishing enabled:

```powershell
./scripts/run.ps1 -Stage
```

The stage connects to `ws://127.0.0.1:8765` by default. Only derived `avatar.state`, `avatar.expression`, and
`avatar.lipsync` events cross this socket. The stream binds only to a loopback address and refuses inbound commands.

## Configure the Local Model

Copy `.env.example` to `.env` if setup has not already created it. These are the v0.3 defaults:

```dotenv
PAIX_DEFAULT_PROVIDER=local
PAIX_LOCAL_MODEL=paix-local
PAIX_LOCAL_BASE_URL=http://127.0.0.1:1234/v1
PAIX_STAGE_HOST=127.0.0.1
PAIX_STAGE_PORT=8765

ELEVENLABS_API_KEY=
PAIX_ELEVENLABS_VOICE_ID=
PAIX_ELEVENLABS_MODEL=eleven_flash_v2_5
PAIX_TTS_OUTPUT_FORMAT=pcm_24000
```

The normal provider ID is `local`. `scripts/start-local-model.ps1` downloads Qwen3.5 4B Q4_K_M when needed,
starts LM Studio on loopback only, and loads the model into GPU memory as `paix-local`. This localhost HTTP endpoint
is internal communication between Paix and LM Studio on this PC; it is not an internet API. Paix rejects non-loopback
URLs for the local provider and does not fall back to a cloud model.

The `mock`, `openai`, `anthropic`, and `openrouter` adapters remain available only when explicitly selected. Automated
tests always use mocks and never contact the local server or paid providers.

New settings use the `PAIX_*` namespace. Legacy `SYLPHIETTE_*` environment variables and credentials stored under the previous Windows Credential Manager service remain readable for migration compatibility.

ElevenLabs can use the git-ignored server-only key file instead of `.env`:

```powershell
./scripts/import-elevenlabs-key.ps1 -SourceKeyFile 'C:\secure\elevenlabs-key.txt'
```

Never place credentials in source files, terminal commands that will enter shell history, screenshots, logs, or bug reports.

## Run the Voice Runtime

Open `paix.code-workspace`, select **Voice: Paix (Local Qwen)** in Run and Debug, and press F5. The pre-launch
task ensures LM Studio and `paix-local` are ready. The first run downloads about 3.4 GB. **Voice: Typed mock test**
is deterministic test mode; it verifies the pipeline but is not a conversational AI.

Or launch from PowerShell:

```powershell
./scripts/run.ps1
```

Controls:

- Speak when `[listening]` appears; a short natural pause submits the sentence automatically.
- Press `Ctrl+C` to stop hands-free mode.
- Use `./scripts/run.ps1 -PushToTalk` only when manually controlled recording is useful for debugging.
- Use the **Voice: Typed mock test** profile for typed pipeline testing.

The first Faster-Whisper use downloads the configured model. `auto` selects CUDA when a GPU is detected and CPU
otherwise, but Paix does not retry on CPU after a CUDA failure. The main VS Code voice profile requires CUDA with
`float16`. On Windows, the speech extra installs the CUDA 12 cuBLAS and cuDNN 9 runtime libraries required by
CTranslate2.

### Select Providers and Devices

```powershell
./scripts/run.ps1 -Provider local -Model paix-local
./scripts/run.ps1 -ListDevices
./scripts/run.ps1 -InputDevice 'Microphone Array' -OutputDevice 'Speakers'
./scripts/run.ps1 -ListVoices
./scripts/run.ps1 -VoiceId '<elevenlabs-voice-id>'
./scripts/run.ps1 -PushToTalk
```

If an ElevenLabs key is configured but no voice ID is set, the runtime attempts to list available voices and asks for a selection. If TTS is unavailable, the conversation still works and prints responses in the terminal.

An ElevenLabs `401 Unauthorized` response means the configured key was rejected. Create a replacement key with
voice-read and text-to-speech access, store only that replacement in `.secrets/elevenlabs.key`, and leave
`ELEVENLABS_API_KEY` empty in `.env` so there is only one active copy to troubleshoot.

### Typed Development Fallback

```powershell
./scripts/run.ps1 -TypedOnly -NoTts
```

This mode does not install or use microphone/audio dependencies when paired with `setup.ps1 -TypedOnly`.

## Architecture

```text
microphone -> Silero VAD endpointing -> WAV in memory -> Faster-Whisper -> transcript
     -> persona + approved memory + recent conversation
     -> loopback LM Studio -> local Qwen3.5 4B -> streamed text
     -> phrase chunker -> ElevenLabs PCM -> speakers
                                      |
                                      +-> avatar adapter -> sanitized loopback stream -> Live2D stage
```

The microphone WAV exists only in memory for the active transcription request and is not saved. Faster-Whisper uses a temporary file internally and deletes it after transcription. The orchestrator persists only text and operational metadata.

Every realtime event carries `session_id`, `turn_id`, `sequence`, and a UTC timestamp. Shutting down cancels active provider/TTS work, stops queued terminal playback, and invalidates late events. Interactive barge-in while speech is playing is a v0.2 milestone.

## Persistence

The primary database for a new installation is `data/paix.db`, an embedded SQLite database managed through async SQLAlchemy. Existing installations continue using their configured database path, so the rename does not lose conversation or memory history. It stores:

- Conversations and messages.
- Memories and memory candidates.
- Persona and emotional-state history.
- Configuration versions.
- Provider usage and latency metrics.

Persona source files remain under `config/persona/` as versioned YAML. JSON is used for API events and memory import/export, not as the main database.

The default conversation ID is `voice-primary`, so context continues across runtime restarts. Pass `-ConversationId` to `scripts/run.ps1` when a separate conversation is wanted.

## Optional Developer API

The API is not needed for normal voice use. Launch **Developer API: FastAPI** in VS Code when inspecting endpoints or testing a future integration. It binds to `127.0.0.1:8000`; interactive documentation is available at `http://127.0.0.1:8000/docs` while it is running.

The canonical WebSocket endpoint remains `/ws/chat`. Browser-specific CORS configuration and browser chat build
tooling have been removed. `/api/avatars` reports registered avatar adapters. The optional renderer has its own
isolated build under `stage/`.
Browser-origin WebSocket connections are rejected by default. A future trusted browser integration must explicitly set `PAIX_ALLOWED_WEBSOCKET_ORIGINS`; non-browser local clients do not send an Origin header.

## Tests and Quality Checks

Automated tests use mock providers and do not contact paid services.

```powershell
cd backend
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Live provider tests remain disabled unless `RUN_LIVE_API_TESTS=1` is explicitly set.

## Troubleshooting

### Voice I/O is not installed

Run `./scripts/setup.ps1`. The default setup includes Faster-Whisper, Silero, NumPy, and sounddevice. Use `-TypedOnly` only when microphone and speaker support are not required.

### No microphone or speaker is selected

Run `./scripts/run.ps1 -ListDevices`, then pass the desired names or numeric IDs through `-InputDevice` and `-OutputDevice`.

### Transcription fails

- Confirm FFmpeg is available on `PATH`.
- Confirm Windows microphone privacy permission permits desktop applications and VS Code.
- Set `PAIX_STT_DEVICE=cpu` for the most compatible path.
- The first run needs internet access to download the selected Faster-Whisper model.

### Spoken output is disabled

- Configure `ELEVENLABS_API_KEY` or import a server-only key file.
- Run `./scripts/run.ps1 -ListVoices` and set `PAIX_ELEVENLABS_VOICE_ID`.
- HTTP 401 or 403 means ElevenLabs rejected the credential or its permissions.
- Keep `PAIX_TTS_OUTPUT_FORMAT=pcm_24000`; the v0.1 terminal player accepts raw PCM output.

### The local model is unavailable

Run `./scripts/start-local-model.ps1`, then retry. Paix deliberately reports the local failure instead of silently
sending conversation or memory context to a cloud provider. Use `-Provider mock -TypedOnly -NoTts` only to verify
orchestration without real generation.

## Roadmap

See `Future_Neuro_like.md`. v0.3 delivered the optional Live2D presence without coupling renderer dependencies
to the voice backend. The planned v0.4 milestone migrates the VTuber to Unity, replaces ElevenLabs with a local
open-source anime-style TTS adapter, moves owner-editable persona/settings/knowledge to schema-validated JSON,
adds fully local RAG, and makes end-to-end debugging available through redacted structured traces and health
checks. Later work adds vision, autonomous reactions, stream-chat integrations, game agents, and singing.
