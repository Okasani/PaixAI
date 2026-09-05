# Paix implementation progress

## v0.4 — Unity VTuber, local anime voice, editable RAG, and diagnostics

- Planned: migrate the licensed VTuber model from the Electron/Pixi stage to a Unity application using the
  official Cubism SDK for Unity while preserving the existing avatar event contract.
- Planned: replace ElevenLabs as the default speech path with a local open-source anime-style TTS adapter; retain
  no automatic cloud fallback.
- Planned: move owner-editable persona, runtime, voice/avatar profile, and curated knowledge sources to documented,
  schema-validated JSON.
- Planned: build a fully local RAG ingestion and retrieval pipeline with rebuildable derived indexes, source
  provenance, and untrusted-context boundaries.
- Planned: add one-command health checks, redacted JSONL turn traces, inspect/rebuild/export tools, and a Unity
  diagnostics overlay.
- Status: roadmap defined; implementation has not started.

## v0.3 — Live2D VTuber presence

- Complete: optional sandboxed Electron/Pixi Live2D Cubism 4 renderer with no dependency impact on the minimal
  typed or voice installation.
- Complete: avatar adapter/registry boundary and loopback-only read-only command stream.
- Complete: canonical listening, transcribing, thinking, speaking, interrupted, idle, and error state mapping.
- Complete: PCM-amplitude lip-sync with attack/release smoothing and automatic mouth closure.
- Complete: bounded emotional-state mapping to configurable model expressions and motions.
- Complete: natural blinking, breathing, gaze saccades, and subtle state-sensitive idle movement.
- Complete: renderer input validation, stale sequence rejection, interruption hold, path confinement, strict CSP,
  context isolation, disabled Node integration, and no private text/audio on the stage stream.
- External asset requirement: the user supplies a licensed Cubism 4 model and Cubism Core runtime.

## v0.2 — Fully local LLM brain

- Complete: Qwen3.5 4B Q4_K_M selected for the 8 GB RTX 3060 Ti and managed through the installed LM Studio runtime.
- Complete: loopback-only `local` provider adapter with streaming, usage, model health, cancellation, and no hidden-reasoning output.
- Complete: local provider is the application, PowerShell, and VS Code voice default; cloud failure never triggers fallback.
- Complete: PowerShell startup downloads the pinned quantization when absent, binds LM Studio to `127.0.0.1`,
  and loads it with the stable `paix-local` identifier.
- Complete: persona instructions now prioritize direct identity answers and natural spoken conversation while rejecting
  the canned phrases seen in the v0.1 mock response.
- Remaining v0.2 voice work: true barge-in during playback, echo control, persistent device selection, and partial
  transcription. Local TTS is promoted to the v0.4 milestone.

## v0.1 — Voice-first AI companion

### Foundation

- Complete: pinned Python 3.11 project, SQLite schema, canonical realtime events, mock streaming, persistence, provider registries, and VS Code debugging.
- Complete: WebUI and Node.js build/runtime paths removed.

### LLM, persona, and memory

- Complete: OpenAI Responses, Anthropic Messages, OpenRouter SSE, and deterministic mock adapters.
- Complete: versioned YAML persona, bounded emotional state, conversation restoration, approved-memory retrieval, candidate extraction, and SQLite persistence.

### Voice output

- Complete: ElevenLabs realtime WebSocket PCM, phrase chunking, early playback events, cancellation, and voice/model discovery.
- Configuration note: a valid ElevenLabs key and voice ID are required for spoken output; text output remains available when TTS is unavailable.

### Voice input

- Complete: hands-free 16 kHz mono PCM capture with Silero speech-start and automatic pause endpointing.
- Complete: optional terminal push-to-talk mode retained only for debugging.
- Complete: in-memory WAV construction and local Faster-Whisper transcription with explicit device selection,
  strict CUDA errors, and project-managed Windows CUDA 12 speech runtime libraries.
- Complete: transcript submission directly into the existing orchestration pipeline.
- Complete: input/output device discovery and selection.

### Developer experience

- Complete: `Voice: Paix`, typed fallback, and optional developer API VS Code launch configurations.
- Complete: PowerShell and shell setup/run scripts no longer require a frontend or browser.
- Complete: persistent `voice-primary` conversation plus provider, model, voice, and device CLI overrides.

## Deferred milestones

- v0.2 continuation: immediate barge-in during playback, echo control, persistent device configuration, and
  partial transcription.
- v0.4: Unity renderer migration, local open-source anime-style TTS, editable JSON configuration and knowledge,
  local RAG, and structured diagnostics.
- Later: vision, autonomous activity, stream-chat integrations, game agents, and singing.

## Verification

- Automated checks use mock providers and never contact paid APIs.
- Complete: backend tests include a mock-transport local-provider contract and never contact the model server.
- Complete: Ruff lint and formatting checks pass across all Python sources.
- Complete: PowerShell setup/run scripts parse successfully.
- Complete: Live2D stage unit tests, TypeScript type checks, production build, dependency audit, and Electron startup
  smoke test pass.
- Complete: sounddevice detects the local microphone and speaker devices.
- Live microphone and legacy ElevenLabs generation require explicit local runtime verification.
