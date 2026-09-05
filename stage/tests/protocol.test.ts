import { describe, expect, it } from "vitest";

import { parseAvatarEvent } from "../src/protocol";

describe("parseAvatarEvent", () => {
  it("accepts a canonical UTC avatar event", () => {
    expect(
      parseAvatarEvent({
        type: "avatar.state",
        session_id: "session",
        turn_id: "turn",
        sequence: 1,
        timestamp: "2026-01-01T00:00:00Z",
        payload: { state: "idle" },
      }),
    ).not.toBeNull();
  });

  it("rejects raw conversation events and incomplete envelopes", () => {
    expect(
      parseAvatarEvent({
        type: "text.delta",
        session_id: "session",
        turn_id: "turn",
        sequence: 1,
        timestamp: "2026-01-01T00:00:00Z",
        payload: { text: "private" },
      }),
    ).toBeNull();
    expect(parseAvatarEvent({ type: "avatar.state", payload: {} })).toBeNull();
  });
});
