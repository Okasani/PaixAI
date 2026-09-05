import type { AvatarEvent, AvatarState } from "./protocol";

export interface AvatarDriver {
  setParameter(id: string, value: number): void;
  playMotion(group: string): void;
  setExpression(expression: string, intensity: number): void;
  setState(state: AvatarState): void;
}

interface ControllerOptions {
  motionGroups?: Record<string, string>;
  expressions?: Record<string, string>;
  random?: () => number;
  now?: () => number;
}

const avatarStates = new Set<AvatarState>([
  "idle",
  "listening",
  "transcribing",
  "thinking",
  "speaking",
  "interrupted",
  "error",
]);

export class AvatarMotionController {
  state: AvatarState = "idle";
  private readonly driver: AvatarDriver;
  private readonly motionGroups: Record<string, string>;
  private readonly expressions: Record<string, string>;
  private readonly random: () => number;
  private readonly now: () => number;
  private readonly lastSequence = new Map<string, number>();
  private mouth = 0;
  private mouthTarget = 0;
  private mouthExpiresAt = 0;
  private elapsed = 0;
  private nextBlinkAt: number;
  private blinkStartedAt: number | null = null;
  private nextGazeAt: number;
  private gazeX = 0;
  private gazeY = 0;
  private gazeTargetX = 0;
  private gazeTargetY = 0;
  private stateHoldUntil = 0;
  private pendingState: { state: AvatarState; motion: string } | null = null;

  constructor(driver: AvatarDriver, options: ControllerOptions = {}) {
    this.driver = driver;
    this.motionGroups = options.motionGroups || {};
    this.expressions = options.expressions || {};
    this.random = options.random || Math.random;
    this.now = options.now || (() => performance.now());
    const started = this.now();
    this.nextBlinkAt = started + this.blinkDelay();
    this.nextGazeAt = started + this.gazeDelay();
  }

  apply(event: AvatarEvent): boolean {
    const previous = this.lastSequence.get(event.session_id) ?? -1;
    if (event.sequence <= previous) return false;
    this.lastSequence.set(event.session_id, event.sequence);
    const now = this.now();

    if (event.type === "avatar.state") {
      const rawState = String(event.payload.state || "");
      if (!avatarStates.has(rawState as AvatarState)) return false;
      const state = rawState as AvatarState;
      const motion = String(event.payload.motion || state);
      if (this.state === "interrupted" && state === "idle" && now < this.stateHoldUntil) {
        this.pendingState = { state, motion };
        return true;
      }
      this.applyState(state, motion);
      const holdMs = Number(event.payload.hold_ms || 0);
      this.stateHoldUntil = holdMs > 0 ? now + Math.min(2000, holdMs) : 0;
      return true;
    }

    if (event.type === "avatar.expression") {
      const semantic = String(event.payload.expression || "neutral");
      const mapped = this.expressions[semantic] ?? semantic;
      const intensity = clamp(Number(event.payload.intensity || 0.5), 0, 1);
      this.driver.setExpression(mapped, intensity);
      return true;
    }

    const target = clamp(Number(event.payload.mouth_open || 0), 0, 1);
    const duration = clamp(Number(event.payload.duration_ms || 80), 0, 1000);
    this.mouthTarget = target;
    this.mouthExpiresAt = now + Math.max(80, duration + 40);
    return true;
  }

  tick(deltaMs: number): void {
    const now = this.now();
    this.elapsed += Math.max(0, deltaMs) / 1000;
    if (this.pendingState && now >= this.stateHoldUntil) {
      const pending = this.pendingState;
      this.pendingState = null;
      this.applyState(pending.state, pending.motion);
    }
    if (now >= this.mouthExpiresAt) this.mouthTarget = 0;
    const mouthRate = this.mouthTarget > this.mouth ? 0.46 : 0.28;
    this.mouth += (this.mouthTarget - this.mouth) * mouthRate;
    if (Math.abs(this.mouth) < 0.002) this.mouth = 0;
    this.driver.setParameter("ParamMouthOpenY", this.mouth);

    this.updateBlink(now);
    this.updateGaze(now);
    const energy = this.state === "speaking" ? 1.35 : this.state === "thinking" ? 0.72 : 1;
    this.driver.setParameter("ParamBreath", 0.5 + Math.sin(this.elapsed * 1.65) * 0.5);
    this.driver.setParameter("ParamBodyAngleX", Math.sin(this.elapsed * 0.72) * 1.6 * energy);
    this.driver.setParameter("ParamAngleZ", Math.sin(this.elapsed * 0.54) * 1.15 * energy);
  }

  private applyState(state: AvatarState, semanticMotion: string): void {
    this.state = state;
    this.driver.setState(state);
    const motion = this.motionGroups[semanticMotion] ?? this.motionGroups[state] ?? semanticMotion;
    if (motion) this.driver.playMotion(motion);
  }

  private updateBlink(now: number): void {
    if (this.blinkStartedAt === null && now >= this.nextBlinkAt) this.blinkStartedAt = now;
    let eyeOpen = 1;
    if (this.blinkStartedAt !== null) {
      const progress = (now - this.blinkStartedAt) / 180;
      if (progress >= 1) {
        this.blinkStartedAt = null;
        this.nextBlinkAt = now + this.blinkDelay();
      } else {
        eyeOpen = progress < 0.45 ? 1 - progress / 0.45 : (progress - 0.45) / 0.55;
      }
    }
    this.driver.setParameter("ParamEyeLOpen", clamp(eyeOpen, 0, 1));
    this.driver.setParameter("ParamEyeROpen", clamp(eyeOpen, 0, 1));
  }

  private updateGaze(now: number): void {
    if (now >= this.nextGazeAt) {
      this.gazeTargetX = (this.random() * 2 - 1) * 0.72;
      this.gazeTargetY = (this.random() * 2 - 1) * 0.48;
      this.nextGazeAt = now + this.gazeDelay();
    }
    this.gazeX += (this.gazeTargetX - this.gazeX) * 0.025;
    this.gazeY += (this.gazeTargetY - this.gazeY) * 0.025;
    this.driver.setParameter("ParamEyeBallX", this.gazeX);
    this.driver.setParameter("ParamEyeBallY", this.gazeY);
    this.driver.setParameter("ParamAngleX", this.gazeX * 4.5);
    this.driver.setParameter("ParamAngleY", this.gazeY * 3.2);
  }

  private blinkDelay(): number {
    return 2200 + this.random() * 3200;
  }

  private gazeDelay(): number {
    return 1800 + this.random() * 2600;
  }
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Number.isFinite(value) ? Math.min(maximum, Math.max(minimum, value)) : minimum;
}
