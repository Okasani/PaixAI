import { describe, expect, it } from "vitest";

import { augmentModelManifest } from "../electron/model-manifest";

describe("augmentModelManifest", () => {
  it("registers VTube Studio sidecar expressions and motions", () => {
    const model = { Version: 3, FileReferences: { Moc: "witch.moc3" } };

    const result = augmentModelManifest(model, ["smile.exp3.json", "Scene1.motion3.json"]) as {
      FileReferences: Record<string, unknown>;
    };

    expect(result.FileReferences.Expressions).toEqual([{ Name: "smile", File: "smile.exp3.json" }]);
    expect(result.FileReferences.Motions).toEqual({
      Idle: [{ File: "Scene1.motion3.json", FadeInTime: 0.5, FadeOutTime: 0.5 }],
    });
  });

  it("preserves expression and motion declarations already present in the model", () => {
    const expressions = [{ Name: "existing", File: "existing.exp3.json" }];
    const motions = { Tap: [{ File: "tap.motion3.json" }] };
    const model = { FileReferences: { Expressions: expressions, Motions: motions } };

    const result = augmentModelManifest(model, ["other.exp3.json", "other.motion3.json"]) as {
      FileReferences: Record<string, unknown>;
    };

    expect(result.FileReferences.Expressions).toBe(expressions);
    expect(result.FileReferences.Motions).toBe(motions);
  });
});
