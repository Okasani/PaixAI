export {};

interface PaixStageConfig {
  modelUrl: string | null;
  coreUrl: string | null;
  socketUrl: string;
  motionGroups: Record<string, string>;
  expressions: Record<string, string>;
}

declare global {
  interface Window {
    paixStage: {
      getConfig(): Promise<PaixStageConfig>;
      selectModel(): Promise<PaixStageConfig>;
      selectCore(): Promise<PaixStageConfig>;
      close(): Promise<void>;
    };
    Live2DCubismCore?: unknown;
  }
}
