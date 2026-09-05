# Paix Unity stage

Targets Unity 2022.3 LTS and a compatible official Cubism SDK for Unity. SDK, Core runtime, and character assets
are supplied separately under their own licenses. Compilation and actual rendering remain release acceptance checks.

1. Open this directory in Unity. Restore Newtonsoft JSON from `Packages/manifest.json`.
2. Import a compatible [official Cubism SDK](https://www.live2d.com/en/sdk/download/unity/).
3. Choose **Paix → Enable installed Cubism SDK** to enable `PAIX_CUBISM` after checking for the SDK directory.
4. Import your licensed `.model3.json` and dependencies under `Assets/Models/` with the Original Workflow importer.
   Include expressions and motions. These files are git-ignored.
5. Select the generated model prefab, then choose **Paix → Create stage from selected model prefab**. Save any
   existing scene when prompted. This creates a camera, connection component, and model driver.
6. Ensure the model has Cubism update, expression, and motion/fade controllers with expression/fade-motion lists.
   The driver attaches to the model and applies buffered parameters before physics. Configure its motion bindings
   in the Inspector and loop only appropriate state/idle clips.
7. In repository `config/avatar.json`, map motions to the driver's binding names and expressions to imported
   expression-object names. Restart Python after changing mappings.
8. Start Python with `--stage`, then press Play. Default endpoint: `ws://127.0.0.1:8765`. A custom port must match
   both `config/runtime.json` and the stage Endpoint inspector field.
9. Choose **Paix → Build Windows stage** for `Builds/Paix.exe`. The scene and licensed assets remain local.

The client accepts only loopback WebSockets, validates bounded JSON and UTC envelopes, rejects private fields and
stale sequences, bounds its queue, and reconnects. Disconnect/non-speaking states close the mouth. Interruption
holds briefly before idle. Procedural animation includes blink, breath, gaze and state-sensitive body motion.

The overlay shows connection, state, selected motion/expression indexes, mouth level, FPS, model readiness, and
safe error codes. It never displays received text or exception content. Expression intensity travels in the
protocol; the driver uses Cubism's configured blending instead of scaling expression parameters by that intensity.

Python owns audio playback. Local TTS emits paced PCM chunks and corresponding mouth amplitudes. Actual alignment,
model framing and every motion/expression must pass hardware acceptance before retiring Electron.

Standalone tests: `scripts/test-unity-protocol.ps1` from the repository root, or
`dotnet run --project unity/Tests/ProtocolTests.csproj` with .NET 8 SDK. These do not compile Unity-dependent scripts.

References: [Cubism expressions](https://docs.live2d.com/en/cubism-sdk-tutorials/expression/) and
[Cubism motion](https://docs.live2d.com/en/cubism-sdk-manual/motion-unity/).
