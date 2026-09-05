# Paix implementation progress

## v0.4 — Implementation available; live release gates pending

- Implemented: JSON persona, runtime, voice and avatar profiles, generated JSON Schemas, input-free validation errors,
  environment/CLI precedence, and canonical GitHub repository instructions.
- Implemented: deterministic CPU-only sparse TF-IDF retrieval with explicit text/Markdown ingestion, JSON sources,
  provenance, atomic rebuilds, stale-index detection, query/inspect/export/backup commands, and escaped untrusted context.
- Implemented: TTS adapter registry with a local Style-Bert-VITS2 default, explicit legacy ElevenLabs selection,
  deterministic mock audio, bounded PCM responses, phrase streaming, and cancellation without cloud fallback.
- Implemented: a separate optional local voice bridge with offline model loading, suppressed third-party output,
  loopback JSON requests, and an inference worker that is terminated when a request is cancelled.
- Implemented: Unity project sources, strict event parsing, bounded reconnect queue, state/animation controller,
  Cubism driver, stage creation/build menu, and diagnostics overlay. Original Electron stage remains available.
- Implemented: opt-in content-free rotating JSONL traces, safe export, health checks, mock spoken-turn smoke test,
  GitHub Actions checks, and a Codespaces backend configuration.
- Verified locally: backend mock tests and standalone C# protocol/controller tests. See docs/v0.4.md for commands.
- Pending release gates: compile/build the Unity application with the licensed Cubism SDK/model; verify expressions,
  motions and actual playback lip-sync; supply an approved voice and local language resources; benchmark a real spoken
  turn and concurrent VRAM use on the 8 GB target GPU. No live voice quality or latency claim is made yet.
- Status: v0.4 is not release-complete until these live gates pass. No release tag is created.

## v0.3 â€” Live2D VTuber presence

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

## v0.2 â€” Fully local LLM brain

- Complete: Qwen3.5 4B Q4_K_M selected for the 8 GB RTX 3060 Ti and managed through the installed LM Studio runtime.
- Complete: loopback-only `local` provider adapter with streaming, usage, model health, cancellation, and no hidden-reasoning output.
- Complete: local provider is the application, PowerShell, and VS Code voice default; cloud failure never triggers fallback.
- Complete: PowerShell startup downloads the pinned quantization when absent, binds LM Studio to `127.0.0.1`,
  and loads it with the stable `paix-local` identifier.
- Complete: persona instructions now prioritize direct identity answers and natural spoken conversation while rejecting
  the canned phrases seen in the v0.1 mock response.
- Remaining v0.2 voice work: true barge-in during playback, echo control, persistent device selection, and partial
  transcription. Local TTS is promoted to the v0.4 milestone.

## v0.1 â€” Voice-first AI companion

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
- v0.4 release verification: licensed Unity build, local voice setup, and end-to-end hardware acceptance.
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
