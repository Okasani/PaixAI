# Changelog

All notable Project Paix changes are recorded here. Earlier implementation history remains available in
`PROGRESS.md`.

## [0.4.0] - Unreleased

### Added

- Unity stage sources and Cubism integration with strict avatar protocol validation, stale-sequence rejection,
  interruption hold, procedural idle movement, mouth closure, diagnostics overlay, and editor setup/build commands.
- Local Style-Bert-VITS2 TTS adapter and optional isolated bridge, with phrase-level PCM, bounded responses,
  cancellation, approved local assets, and no automatic cloud fallback.
- Documented JSON source files and generated schemas for runtime, persona, voice, avatar, and knowledge.
- CPU-only local sparse TF-IDF retrieval, source offsets/hashes, deterministic atomic rebuilds, stale-index detection,
  explicit document import, inspect/query/export/backup commands, and prompt injection boundaries.
- Content-free trace recording/export, health diagnostics, and an isolated mock spoken-turn smoke test.
- GitHub Actions validation and a minimal Codespaces backend environment.

### Changed

- Local TTS is the default; ElevenLabs must be selected explicitly as a legacy provider.
- Persona sources and API edits use JSON. SQLite conversation and memory storage remains intact.
- Canonical development repository is https://github.com/Okasani/PaixAI.
- Optional STT tests inject a mock instead of depending on a speech installation.
- Bug report export excludes arbitrary submitted content and local paths.

### Release gates

Unity compilation/rendering with licensed assets and actual local voice quality, latency, cancellation, and 8 GB GPU
coexistence still require live validation. Electron remains a migration fallback. This is an unreleased implementation.

## [0.3.0] - 2026-09-05

### Added

- Optional sandboxed Electron/Pixi Live2D Cubism 4 stage, isolated from the minimal Python voice and typed runtime.
- Avatar adapter registry with canonical mappings for idle, listening, transcribing, thinking, speaking,
  interrupted, and error states.
- Loopback-only, read-only WebSocket stage transport that publishes derived avatar commands without exposing
  conversation text, prompts, tool results, raw microphone audio, or raw TTS audio.
- PCM-amplitude lip-sync with attack/release smoothing and automatic mouth closure.
- Bounded emotional-state mapping to configurable Live2D expressions and motion groups.
- Procedural blink, breath, gaze, and subtle idle animation, including an interruption reaction hold.
- Local model/Core file selection, confined asset protocol, example stage configuration, setup/run scripts, and
  VS Code launch/task entries.
- Non-destructive discovery of VTube Studio expression and motion sidecars omitted from a source `.model3.json`.
- Backend and renderer tests covering event envelopes, privacy filtering, loopback enforcement, stale sequences,
  state/expression mapping, lip-sync, interruption behavior, and idle motion parameters.

### Changed

- Project and backend version advanced from 0.2.0 to 0.3.0.
- The voice CLI accepts `--stage`; PowerShell accepts `-Stage`.
- The orchestrator emits bounded `emotion.state` events for avatar expression mapping.
- The developer API exposes registered avatar manifests at `/api/avatars`.
- Pixi shader uniform updates use its CSP-compatible static adapter, so Live2D renders without enabling
  `unsafe-eval` in Electron.
- Cubism Core 5 render orders are bridged to the Cubism 4 renderer API, the character is bottom-anchored within
  the stage, and startup now rejects an empty first frame instead of hiding the setup diagnostics.

### Security

- The stage socket can bind only to localhost or another loopback address and rejects inbound commands.
- The renderer validates canonical event envelopes and ignores malformed or stale events.
- Electron runs with context isolation, renderer sandboxing, disabled Node integration, a strict content security
  policy, and path-confined access to user-selected model assets.
- Cubism Core and character assets are not redistributed; users must provide files they are licensed to use.
- Renderer dependencies are locked, and the v0.3 dependency audit reports no known vulnerabilities.
