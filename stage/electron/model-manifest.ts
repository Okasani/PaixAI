function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/** Add VTube Studio sidecar expressions/motions without modifying the source package. */
export function augmentModelManifest(value: unknown, fileNames: string[]): unknown {
  const model = record(value);
  if (!model) return value;
  const references = record(model.FileReferences) || {};
  model.FileReferences = references;

  const expressionFiles = fileNames.filter((name) => name.toLowerCase().endsWith(".exp3.json")).sort();
  const currentExpressions = Array.isArray(references.Expressions) ? references.Expressions : [];
  if (currentExpressions.length === 0 && expressionFiles.length > 0) {
    references.Expressions = expressionFiles.map((file) => ({
      Name: file.replace(/\.exp3\.json$/i, ""),
      File: file,
    }));
  }

  const motionFiles = fileNames.filter((name) => name.toLowerCase().endsWith(".motion3.json")).sort();
  const currentMotions = record(references.Motions);
  if ((!currentMotions || Object.keys(currentMotions).length === 0) && motionFiles.length > 0) {
    references.Motions = {
      Idle: motionFiles.map((file) => ({ File: file, FadeInTime: 0.5, FadeOutTime: 0.5 })),
    };
  }
  return model;
}
