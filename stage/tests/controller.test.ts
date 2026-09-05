import { describe, expect, it } from "vitest";

import { AvatarMotionController, type AvatarDriver } from "../src/controller";
import type { AvatarEvent, AvatarState } from "../src/protocol";

class FakeDriver implements AvatarDriver {
  parameters = new Map<string, number>();
  motions: string[] = [];
  expressions: string[] = [];
  states: AvatarState[] = [];

  setParameter(id: string, value: number): void {
    this.parameters.set(id, value);
  }

  playMotion(group: string): void {
    this.motions.push(group);
  }

  setExpression(expression: string): void {
    this.expressions.push(expression);
  }

  setState(state: AvatarState): void {
    this.states.push(state);
  }
}

function event(type: AvatarEvent["type"], sequence: number, payload: Record<string, unknown>): AvatarEvent {
  return {
    type,
    session_id: "test-session",
    turn_id: "test-turn",
    sequence,
    timestamp: "2026-01-01T00:00:00Z",
    payload,
  };
}

describe("AvatarMotionController", () => {
  it("maps states and rejects stale events", () => {
    const driver = new FakeDriver();
    const controller = new AvatarMotionController(driver, {
      motionGroups: { speaking: "Talk" },
      now: () => 1000,
      random: () => 0.5,
    });

    expect(controller.apply(event("avatar.state", 3, { state: "speaking", motion: "speaking" }))).toBe(true);
    expect(controller.apply(event("avatar.state", 2, { state: "idle", motion: "idle" }))).toBe(false);
    expect(controller.state).toBe("speaking");
    expect(driver.motions).toEqual(["Talk"]);
  });

  it("smooths lipsync and closes the mouth after the chunk expires", () => {
    let now = 1000;
    const driver = new FakeDriver();
    const controller = new AvatarMotionController(driver, { now: () => now, random: () => 0.5 });

    controller.apply(event("avatar.lipsync", 1, { mouth_open: 1, duration_ms: 100 }));
    controller.tick(16);
    expect(driver.parameters.get("ParamMouthOpenY")).toBeGreaterThan(0);

    now = 1300;
    controller.tick(16);
    expect(driver.parameters.get("ParamMouthOpenY")).toBeLessThan(0.8);
  });

  it("holds interrupted state briefly before returning to idle", () => {
    let now = 1000;
    const driver = new FakeDriver();
    const controller = new AvatarMotionController(driver, { now: () => now, random: () => 0.5 });

    controller.apply(event("avatar.state", 1, { state: "interrupted", motion: "interrupted", hold_ms: 450 }));
    controller.apply(event("avatar.state", 2, { state: "idle", motion: "idle" }));
    expect(controller.state).toBe("interrupted");

    now = 1500;
    controller.tick(16);
    expect(controller.state).toBe("idle");
  });

  it("drives expression, blink, breathing, gaze, and idle movement parameters", () => {
    let now = 1000;
    const driver = new FakeDriver();
    const controller = new AvatarMotionController(driver, {
      expressions: { warm: "Smile" },
      now: () => now,
      random: () => 0,
    });

    controller.apply(event("avatar.expression", 1, { expression: "warm", intensity: 0.8 }));
    now = 4000;
    controller.tick(16);

    expect(driver.expressions).toEqual(["Smile"]);
    expect(driver.parameters.has("ParamEyeLOpen")).toBe(true);
    expect(driver.parameters.has("ParamBreath")).toBe(true);
    expect(driver.parameters.has("ParamEyeBallX")).toBe(true);
    expect(driver.parameters.has("ParamBodyAngleX")).toBe(true);
  });
});
