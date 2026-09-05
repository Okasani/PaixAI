import type { AvatarDriver } from "./controller";
import type { AvatarState } from "./protocol";

interface Live2DModelLike {
  internalModel: {
    coreModel: {
      setParameterValueById(id: string, value: number): void;
    };
    motionManager?: {
      expressionManager?: {
        resetExpression(): void;
      };
    };
  };
  motion(group: string): Promise<boolean>;
  expression(expression: string): Promise<boolean>;
}

export class Live2DDriver implements AvatarDriver {
  private readonly model: Live2DModelLike;
  private lastMotion = "";
  private lastExpression = "";

  constructor(model: unknown) {
    this.model = model as Live2DModelLike;
  }

  setParameter(id: string, value: number): void {
    try {
      this.model.internalModel.coreModel.setParameterValueById(id, value);
    } catch {
      // Live2D parameter sets vary by model; unsupported optional parameters are ignored.
    }
  }

  playMotion(group: string): void {
    if (!group || group === this.lastMotion) return;
    this.lastMotion = group;
    void this.model.motion(group).catch(() => undefined);
  }

  setExpression(expression: string, _intensity: number): void {
    if (expression === this.lastExpression) return;
    if (!expression) {
      this.model.internalModel.motionManager?.expressionManager?.resetExpression();
      this.lastExpression = "";
      return;
    }
    this.lastExpression = expression;
    void this.model.expression(expression).catch(() => undefined);
  }

  setState(_state: AvatarState): void {
    // State is reflected through motion, expression, and procedural parameters.
  }
}
