# Future Neuro-like Direction

Paix's long-term direction is an AI VTuber closer to Neuro-sama. v0.1 established the conversational voice core,
v0.2 moved the LLM brain local, and v0.3 added the first visual character. v0.4 moves that character to Unity,
replaces the temporary cloud TTS path, and makes Paix's knowledge and diagnostics practical for the owner to edit.

## Product Decision

The WebUI is discarded. There will be no browser chat page or developer Control Center. Development, typed fallback conversations, configuration, tests, and diagnostics can be handled through VS Code, the terminal, configuration files, SQLite tools, and the optional local developer API.

An avatar is also intentionally excluded from v0.1. A Live2D model cannot make the project feel alive if listening, thinking, speaking, memory, and interruption are not reliable first.

## v0.1 â€” Voice-first AI Companion

The goal of v0.1 is to talk naturally with Paix through a microphone and hear her spoken response without opening a browser.

### User Experience

- Launch Paix from VS Code or `scripts/run.ps1`.
- Listen continuously and detect speech boundaries automatically with Silero VAD.
- Transcribe speech locally with Faster-Whisper.
- Send the transcript through the existing persona, memory, tool, and LLM pipeline.
- Stream generated text to ElevenLabs and play PCM speech through the selected output device.
- Print transcripts and streamed responses in the VS Code terminal for development visibility.
- Keep `/text` and typed-only mode as development fallbacks.
- Preserve one continuing `voice-primary` conversation in SQLite by default.
- Cancel active generation and stop accepting queued speech when the runtime shuts down.

### v0.1 Architecture

```text
Microphone (16 kHz mono PCM)
            |
            v
 continuous capture + Silero VAD
            |
            v
      Faster-Whisper STT
            |
            v
 persona + memory + tools + LLM
            |
            +--------------------> terminal transcript
            |
            v
  ElevenLabs streaming PCM TTS
            |
            v
       system speakers
```

The voice client runs in the same local Python process as the orchestrator. FastAPI and the canonical WebSocket API remain available for development and future integrations, but neither is required for the primary voice runtime.

### Persistence

Continue using embedded SQLite. It stores conversations, messages, memories, memory candidates, persona state, configuration versions, provider usage, and latency records.

In v0.1, JSON is only an interchange format for APIs, realtime events, and memory import/export, while persona
source configuration remains in YAML. v0.4 deliberately changes the user-editable source format to JSON. SQLite
remains appropriate for generated runtime state; PostgreSQL should only be reconsidered for remote hosting,
multiple users, cross-device shared state, or substantial concurrent writes.

### v0.1 Completion Criteria

- The voice runtime launches directly from VS Code and PowerShell without Node.js or a browser.
- Speaking starts capture automatically and a natural pause submits the utterance without keyboard input.
- Microphone audio is never logged or persisted after transcription.
- Voice input works with local Faster-Whisper on CPU, with optional CUDA acceleration.
- Spoken output streams as PCM when a valid ElevenLabs key and voice are configured.
- Text-only fallback works with the deterministic mock provider.
- Conversations, memories, persona state, usage, and latency continue to persist in SQLite.
- All realtime events include `session_id`, `turn_id`, `sequence`, and an ISO-8601 UTC timestamp.
- Automated tests use only mock providers; live API calls remain explicitly opt-in.

## v0.2 â€” Fully Local LLM Brain

v0.2 replaces the cloud LLM in Paix's normal runtime with a local model. The selected starting model is
Qwen3.5 4B Q4_K_M, hosted by LM Studio on `127.0.0.1`. The stable model identifier is `paix-local`, so the
application does not depend on LM Studio's downloaded filename.

- Make `local` the default LLM provider and make VS Code F5 start and load the model automatically.
- Send persona, approved memory, recent conversation, and user input only to the loopback model endpoint.
- Never fall back to OpenAI, Anthropic, OpenRouter, or another cloud LLM when local inference fails.
- Reject a non-loopback URL in local-provider configuration to prevent accidentally sending private context away.
- Disable model reasoning output for lower voice latency and never expose hidden reasoning fields.
- Strengthen Paix's identity and conversational rules for a small local model: answer intent first, know her name,
  avoid canned coaching language, and keep ordinary voice replies concise and natural.
- Keep cloud adapters available only for explicit developer experiments; they are inactive in the default runtime.
- Evaluate the base model and persona prompt before attempting LoRA. Fine-tuning should solve measured behavior
  failures, not compensate for a broken prompt or pipeline.

"Fully local" in this milestone means Paix's LLM brain. Speech-to-text is already local. ElevenLabs remains the
temporary speech-output adapter, so spoken output still uses that service when enabled; a later local-TTS adapter
will remove that final online dependency.

### Next v0.2 Voice Work

- Allow barge-in while Paix is speaking and stop playback immediately.
- Improve echo handling so speaker output does not retrigger microphone input.
- Add configurable input/output device persistence.
- Improve partial transcription and latency without inventing unsupported partial results.

Local TTS is now a primary v0.4 migration rather than an optional v0.2 follow-up.

## v0.3 â€” Live2D VTuber Presence â€” Implemented

- Add the Live2D renderer only after the voice loop is reliable.
- Create an avatar adapter and registry boundary so rendering remains independent of conversation and provider code.
- Map canonical listening, thinking, speaking, interrupted, idle, and error states to animation.
- Drive lip-sync from PCM amplitude first, then use phoneme or viseme timing when a provider exposes it.
- Map bounded emotional state to expressions and motions.
- Add natural blinking, breathing, gaze, and subtle idle movement.

### v0.3 Implementation

- The renderer is an optional, sandboxed Electron process under `stage/`; the Python typed/voice installation
  remains free of Node, Electron, Pixi, Cubism, and model dependencies.
- A registered `live2d` avatar adapter converts canonical runtime events into `avatar.state`, `avatar.expression`,
  and `avatar.lipsync` commands without forwarding private conversation or audio content.
- The voice runtime publishes those commands over a loopback-only, read-only WebSocket when `--stage` is enabled.
- The stage validates every envelope, rejects stale sequences, smooths mouth movement, holds interruption reactions,
  maps semantic motions/expressions through local configuration, and procedurally drives blink, breath, gaze, and
  idle movement.
- Cubism Core and character assets remain user-supplied so their separate licenses are respected.

## v0.4 â€” Unity VTuber, Local Anime Voice, and Editable RAG â€” Planned

Implementation status and remaining live release gates are tracked in `PROGRESS.md` and `docs/v0.4.md`.
The following describes the target acceptance scope.

The v0.4 goal is a fully local character runtime that is easier for the owner to customize and diagnose. Unity
becomes the presentation layer, an open-source anime-style TTS provider becomes the normal speech path, and
editable JSON knowledge is retrieved through a local RAG pipeline. ElevenLabs is not part of the future default
architecture.

### Unity avatar runtime

- Create a Unity project for the VTuber window and import the licensed Cubism model through the official Cubism
  SDK for Unity.
- Preserve the avatar adapter boundary and canonical event contract instead of coupling Unity to the LLM,
  memory, or speech implementations.
- Carry over idle, listening, thinking, speaking, interrupted, and error states; expression mapping; natural
  blink, breath, gaze, and motion; and audio-derived lip-sync.
- Keep communication loopback-only and require `session_id`, `turn_id`, `sequence`, and an ISO-8601 UTC timestamp
  on every realtime event.
- Keep the Electron stage as a migration fallback until Unity reaches feature parity, then retire it rather than
  maintaining two permanent renderers.

### Open-source anime-style TTS

- Replace ElevenLabs as the normal TTS provider with a fully local, open-source anime-style voice engine.
- Keep TTS behind a provider adapter and registry so the selected engine and voice weights can be changed without
  rewriting orchestration code.
- Evaluate candidate engines and voice models for license clarity, Windows setup, streaming PCM support,
  cancellation, first-audio latency, output quality, and operation within the target 8 GB GPU budget.
- Treat voice models and weights as user-supplied licensed assets. Never download or enable a voice with unclear
  redistribution or impersonation rights.
- Never fall back to ElevenLabs or another cloud TTS service when local synthesis fails. ElevenLabs remains only
  as a legacy v0.1-v0.3 adapter until migration is complete.

### User-editable JSON and local RAG

- Make documented JSON files the source of truth for user-editable runtime settings, persona data, voice/avatar
  profiles, and curated knowledge. Editing Paix should not require modifying Python or opening SQLite.
- Publish JSON Schemas, example files, stable field names, and precise validation errors that identify the file
  and JSON path without exposing secrets.
- Keep source documents separate from generated chunks, embeddings, and indexes so the derived RAG store can be
  deleted and rebuilt at any time.
- Add local ingestion, chunking, embedding, indexing, and retrieval for JSON knowledge plus explicitly imported
  documents. Store source identity and chunk provenance with every retrieval result.
- Treat retrieved text as untrusted context, never as higher-priority instructions, and keep all embedding and
  retrieval traffic local by default.
- Provide explicit validate, rebuild, inspect, export, and backup commands; reject invalid edits atomically rather
  than partially updating live state.

### Debugging and diagnostics

- Add a single diagnostics command that checks the local LLM, STT, TTS, RAG index, Unity connection, audio
  devices, configuration validity, ports, and optional GPU acceleration.
- Write opt-in, redacted JSONL traces using the canonical event identifiers so a failed turn can be followed from
  microphone state through retrieval, generation, synthesis, and avatar animation.
- Add a Unity debug overlay for connection health, current avatar state, motion/expression selection, lip-sync
  level, frame rate, and the last safe error code.
- Make diagnostic bundles safe to share: never include secrets, authorization headers, raw microphone audio,
  hidden model reasoning, or unrestricted conversation and retrieved-document contents.
- Keep automated tests deterministic with mock providers and add a local smoke-test command that reports each
  subsystem as pass, fail, skipped, or unavailable.

### v0.4 completion criteria

- The licensed VTuber model renders and responds to Paix events in Unity with parity to the v0.3 stage.
- Paix can complete a spoken turn using local STT, the local LLM, and local anime-style TTS with no paid API key
  and no silent cloud fallback.
- The owner can change documented JSON persona, avatar, voice, and knowledge files, validate them, rebuild RAG,
  and see the change without editing application code or the database.
- RAG answers retain source provenance, retrieved content is isolated as untrusted data, and rebuilding the index
  produces deterministic results for unchanged inputs.
- A failed end-to-end turn can be diagnosed from redacted structured traces and health checks without enabling
  unrestricted debug logging.

## Later Neuro-like Capabilities

- Screen and camera vision.
- Autonomous reactions and activity selection.
- Twitch and YouTube chat integration with moderation.
- Game-specific control agents.
- A separate singing pipeline.

These capabilities must build on canonical event contracts, cancellation, untrusted-data handling, security boundaries, and adapter registries instead of coupling directly to one provider or renderer.
