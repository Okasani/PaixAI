import "./styles.css";

import { AvatarMotionController } from "./controller";
import { ensureCubismRenderOrders } from "./cubism-compat";
import { Live2DDriver } from "./live2d-driver";
import { parseAvatarEvent, type AvatarEvent } from "./protocol";

function requiredElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Live2D stage element is missing: ${selector}`);
  return element;
}

const canvas = requiredElement<HTMLCanvasElement>("#avatar-canvas");
const setup = requiredElement<HTMLElement>("#setup");
const setupMessage = requiredElement<HTMLElement>("#setup-message");
const chooseModel = requiredElement<HTMLButtonElement>("#choose-model");
const chooseCore = requiredElement<HTMLButtonElement>("#choose-core");
const closeStage = requiredElement<HTMLButtonElement>("#close-stage");
const stateLabel = requiredElement<HTMLElement>("#state-label");
const connectionDot = requiredElement<HTMLElement>("#connection-dot");

let controller: AvatarMotionController | null = null;
const pendingEvents: AvatarEvent[] = [];

function showSetup(message: string): void {
  setup.hidden = false;
  setupMessage.textContent = message;
}

function canvasHasVisiblePixels(
  gl: WebGLRenderingContext | WebGL2RenderingContext,
  width: number,
  height: number,
): boolean {
  const pixels = new Uint8Array(width * height * 4);
  gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  for (let offset = 3; offset < pixels.length; offset += 4) {
    if (pixels[offset] > 0) return true;
  }
  return false;
}

async function loadScript(url: string): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = url;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Cubism Core could not be loaded"));
    document.head.append(script);
  });
}

function connectStage(socketUrl: string): void {
  let retryMs = 500;
  const connect = () => {
    const socket = new WebSocket(socketUrl);
    stateLabel.textContent = "connecting";
    connectionDot.classList.remove("connected");
    socket.addEventListener("open", () => {
      retryMs = 500;
      stateLabel.textContent = controller?.state || "connected";
      connectionDot.classList.add("connected");
    });
    socket.addEventListener("message", (message) => {
      try {
        const event = parseAvatarEvent(JSON.parse(String(message.data)));
        if (!event) return;
        if (controller) {
          controller.apply(event);
          if (event.type === "avatar.state") stateLabel.textContent = controller.state;
        } else if (pendingEvents.length < 64) {
          pendingEvents.push(event);
        }
      } catch {
        // The stage ignores malformed or untrusted data rather than rendering it.
      }
    });
    socket.addEventListener("close", () => {
      connectionDot.classList.remove("connected");
      stateLabel.textContent = "disconnected";
      window.setTimeout(connect, retryMs);
      retryMs = Math.min(5000, retryMs * 1.7);
    });
    socket.addEventListener("error", () => socket.close());
  };
  connect();
}

async function initialize(): Promise<void> {
  const config = await window.paixStage.getConfig();
  connectStage(config.socketUrl);
  if (!config.modelUrl || !config.coreUrl) {
    const missing = [!config.modelUrl && "a .model3.json file", !config.coreUrl && "Cubism Core"].filter(Boolean);
    showSetup(`Select ${missing.join(" and ")} to start the renderer.`);
    return;
  }
  try {
    await loadScript(config.coreUrl);
    if (!window.Live2DCubismCore) throw new Error("The selected file did not expose Live2DCubismCore");
    const [{ Application, ShaderSystem, Ticker }, { install: installCspSafeShaders }, { Live2DModel }] =
      await Promise.all([
      import("pixi.js"),
      import("@pixi/unsafe-eval"),
      import("pixi-live2d-display/cubism4"),
    ]);
    installCspSafeShaders({ ShaderSystem });
    Live2DModel.registerTicker(Ticker);
    const application = new Application({
      view: canvas,
      resizeTo: window,
      autoDensity: true,
      antialias: true,
      backgroundAlpha: 0,
      resolution: Math.min(2, window.devicePixelRatio || 1),
    });
    const model = await Live2DModel.from(config.modelUrl, { autoInteract: false });
    ensureCubismRenderOrders(model.internalModel.coreModel);
    model.anchor.set(0.5, 1);
    application.stage.addChild(model);

    const fitModel = () => {
      const unscaledWidth = model.width / Math.max(model.scale.x, 0.001);
      const unscaledHeight = model.height / Math.max(model.scale.y, 0.001);
      const scale = Math.min(window.innerWidth / unscaledWidth, window.innerHeight / unscaledHeight) * 0.92;
      model.scale.set(scale);
      model.x = window.innerWidth / 2;
      model.y = window.innerHeight * 0.98;
    };
    fitModel();
    window.addEventListener("resize", fitModel);

    controller = new AvatarMotionController(new Live2DDriver(model), {
      motionGroups: config.motionGroups,
      expressions: config.expressions,
    });
    for (const event of pendingEvents.splice(0)) controller.apply(event);
    let lastModelUpdate = performance.now();
    const internalModel = model.internalModel as unknown as {
      on(event: "beforeModelUpdate", listener: () => void): void;
    };
    internalModel.on("beforeModelUpdate", () => {
      const now = performance.now();
      controller?.tick(Math.min(100, now - lastModelUpdate));
      lastModelUpdate = now;
    });
    application.ticker.add(() => {
      stateLabel.textContent = controller?.state || "idle";
    });
    application.render();
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    if (!gl || !canvasHasVisiblePixels(gl, canvas.width, canvas.height)) {
      throw new Error("Cubism rendered an empty frame");
    }
    setup.hidden = true;
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown Live2D error";
    showSetup(`Live2D could not start: ${message}`);
    stateLabel.textContent = "error";
  }
}

chooseModel.addEventListener("click", async () => {
  await window.paixStage.selectModel();
  window.location.reload();
});
chooseCore.addEventListener("click", async () => {
  await window.paixStage.selectCore();
  window.location.reload();
});
closeStage.addEventListener("click", () => void window.paixStage.close());

void initialize();
