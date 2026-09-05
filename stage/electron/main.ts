import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  net,
  protocol,
} from "electron";
import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { augmentModelManifest } from "./model-manifest.js";

interface StageFileConfig {
  model?: string;
  cubismCore?: string;
  socketUrl?: string;
  alwaysOnTop?: boolean;
  transparent?: boolean;
  width?: number;
  height?: number;
  motionGroups?: Record<string, string>;
  expressions?: Record<string, string>;
}

const stageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const configPath = join(stageRoot, "config.json");

protocol.registerSchemesAsPrivileged([
  {
    scheme: "paix-asset",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
    },
  },
]);

function loadFileConfig(): StageFileConfig {
  if (!existsSync(configPath)) return {};
  try {
    const parsed: unknown = JSON.parse(readFileSync(configPath, "utf8"));
    return parsed && typeof parsed === "object" ? (parsed as StageFileConfig) : {};
  } catch {
    return {};
  }
}

const fileConfig = loadFileConfig();
let modelPath = process.env.PAIX_LIVE2D_MODEL || fileConfig.model || "";
let cubismCorePath = process.env.PAIX_CUBISM_CORE || fileConfig.cubismCore || "";

function persistSelections(): void {
  fileConfig.model = modelPath;
  fileConfig.cubismCore = cubismCorePath;
  writeFileSync(configPath, `${JSON.stringify(fileConfig, null, 2)}\n`, "utf8");
}

function loopbackSocketUrl(value: string | undefined): string {
  const fallback = "ws://127.0.0.1:8765";
  if (!value) return fallback;
  try {
    const parsed = new URL(value);
    const host = parsed.hostname.replace(/^\[|\]$/g, "");
    if (parsed.protocol !== "ws:" || !["127.0.0.1", "localhost", "::1"].includes(host)) return fallback;
    return parsed.toString();
  } catch {
    return fallback;
  }
}

function validFile(path: string, suffix: string): boolean {
  try {
    return path.toLowerCase().endsWith(suffix) && statSync(path).isFile();
  } catch {
    return false;
  }
}

function assetUrl(kind: "model" | "core", path: string): string | null {
  if (!path) return null;
  return `paix-asset://${kind}/${encodeURIComponent(path.split(/[\\/]/).pop() || "")}`;
}

function rendererConfig() {
  const model = validFile(modelPath, ".model3.json") ? assetUrl("model", modelPath) : null;
  const core = validFile(cubismCorePath, ".js") ? assetUrl("core", cubismCorePath) : null;
  return {
    modelUrl: model,
    coreUrl: core,
    socketUrl: loopbackSocketUrl(process.env.PAIX_STAGE_SOCKET_URL || fileConfig.socketUrl),
    motionGroups: fileConfig.motionGroups || {},
    expressions: fileConfig.expressions || {},
  };
}

function resolveAsset(requestUrl: string): string | null {
  const parsed = new URL(requestUrl);
  const kind = parsed.hostname;
  const selected = kind === "model" ? modelPath : kind === "core" ? cubismCorePath : "";
  if (!selected) return null;
  const root = kind === "model" ? dirname(selected) : dirname(cubismCorePath);
  const requested = decodeURIComponent(parsed.pathname).replace(/^\/+/, "");
  const candidate = resolve(root, requested);
  const fromRoot = relative(root, candidate);
  if (!fromRoot || fromRoot.startsWith("..") || isAbsolute(fromRoot)) return null;
  if (kind === "core" && resolve(candidate) !== resolve(cubismCorePath)) return null;
  return candidate;
}

async function createWindow(): Promise<void> {
  const transparent = fileConfig.transparent !== false;
  const window = new BrowserWindow({
    width: Math.max(320, Number(fileConfig.width) || 520),
    height: Math.max(420, Number(fileConfig.height) || 720),
    transparent,
    backgroundColor: transparent ? "#00000000" : "#111827",
    frame: false,
    resizable: true,
    alwaysOnTop: fileConfig.alwaysOnTop !== false,
    show: false,
    webPreferences: {
      preload: join(stageRoot, "electron", "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.once("ready-to-show", () => window.show());
  await window.loadFile(join(stageRoot, "dist", "index.html"));
}

ipcMain.handle("stage:get-config", () => rendererConfig());
ipcMain.handle("stage:select-model", async () => {
  const choice = await dialog.showOpenDialog({
    title: "Select a Live2D Cubism model",
    properties: ["openFile"],
    filters: [{ name: "Cubism model", extensions: ["json"] }],
  });
  const selected = choice.filePaths[0];
  if (!choice.canceled && selected?.toLowerCase().endsWith(".model3.json")) {
    modelPath = selected;
    persistSelections();
  }
  return rendererConfig();
});
ipcMain.handle("stage:select-core", async () => {
  const choice = await dialog.showOpenDialog({
    title: "Select live2dcubismcore.min.js from the official Cubism SDK",
    properties: ["openFile"],
    filters: [{ name: "JavaScript", extensions: ["js"] }],
  });
  const selected = choice.filePaths[0];
  if (!choice.canceled && selected?.toLowerCase().endsWith(".js")) {
    cubismCorePath = selected;
    persistSelections();
  }
  return rendererConfig();
});
ipcMain.handle("stage:close", () => BrowserWindow.getFocusedWindow()?.close());

app.whenReady().then(async () => {
  protocol.handle("paix-asset", (request) => {
    const path = resolveAsset(request.url);
    if (!path) return new Response("Not found", { status: 404 });
    if (new URL(request.url).hostname === "model" && resolve(path) === resolve(modelPath)) {
      try {
        const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
        const augmented = augmentModelManifest(parsed, readdirSync(dirname(path)));
        return new Response(JSON.stringify(augmented), {
          headers: { "content-type": "application/json; charset=utf-8" },
        });
      } catch {
        return new Response("Invalid model manifest", { status: 422 });
      }
    }
    return net.fetch(pathToFileURL(path).toString());
  });
  await createWindow();
});

app.on("window-all-closed", () => app.quit());
