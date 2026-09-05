export type AvatarState =
  | "idle"
  | "listening"
  | "transcribing"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "error";

export interface AvatarEvent {
  type: "avatar.state" | "avatar.expression" | "avatar.lipsync";
  session_id: string;
  turn_id: string;
  sequence: number;
  timestamp: string;
  payload: Record<string, unknown>;
}

const eventTypes = new Set(["avatar.state", "avatar.expression", "avatar.lipsync"]);

export function parseAvatarEvent(value: unknown): AvatarEvent | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.type !== "string" || !eventTypes.has(candidate.type)) return null;
  if (typeof candidate.session_id !== "string" || candidate.session_id.length === 0) return null;
  if (typeof candidate.turn_id !== "string" || candidate.turn_id.length === 0) return null;
  if (!Number.isInteger(candidate.sequence) || Number(candidate.sequence) < 0) return null;
  if (typeof candidate.timestamp !== "string" || !candidate.timestamp.endsWith("Z")) return null;
  if (Number.isNaN(Date.parse(candidate.timestamp))) return null;
  if (!candidate.payload || typeof candidate.payload !== "object" || Array.isArray(candidate.payload)) return null;
  return candidate as unknown as AvatarEvent;
}
