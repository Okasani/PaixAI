# Paix Live2D Stage

The stage is an optional Electron renderer. It connects only to Paix's loopback avatar stream and receives derived
state, expression, motion, and mouth-level commands. It does not receive transcripts, model prompts, tool results,
raw microphone audio, or TTS audio.

## Requirements

- Node.js 20 or newer.
- A Live2D Cubism 4 `.model3.json` model that you are licensed to use.
- `live2dcubismcore.min.js` from the official Live2D Cubism SDK for Web.

The Cubism runtime and model assets are intentionally not redistributed by Paix. Their licenses are separate from
the Paix source license.

## Setup and run

From the project root:

```powershell
./scripts/setup-stage.ps1
./scripts/run-stage.ps1
```

On first launch, select the model and Cubism Core files. The picker persists those paths to the git-ignored
`stage/config.json`. You can also copy `stage/config.example.json` and edit the local paths and mappings manually.

In another terminal, start the voice runtime with avatar publishing enabled:

```powershell
./scripts/run.ps1 -Stage
```

Semantic motion groups and expressions vary between models. Customize `motionGroups` and `expressions` in
`stage/config.json` to match the names defined by your model.

VTube Studio packages sometimes keep `.exp3.json` and `.motion3.json` files beside the model without listing them
in `.model3.json`. The Paix asset protocol discovers those sidecars and augments only the in-memory manifest; it
never rewrites the original model package.
