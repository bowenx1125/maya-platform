import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformApi } from "../lib/api/platform";

import {
  BUSY_MAX_POLL_MS,
  BUSY_MIN_POLL_MS,
  MAX_SERVER_WAIT_MS,
  POLL_AFTER_HEADER,
  PRESSURE_WINDOW_MS,
  nextPollDelay,
  notePollError,
  notePollResponse,
  resetPollPacing,
  serverUnderPressure,
} from "../lib/poll-pacing";

// 60-student rerun (2026-10-19): polling every 1-1.5 s while the server was
// busy kept it busy. Busy signals now slow every poller to 5-10 s.
function response(status: number, headers: Record<string, string> = {}) {
  const map = new Map(
    Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]),
  );
  return {
    status,
    headers: { get: (name: string) => map.get(name.toLowerCase()) ?? null },
  };
}

describe("poll pacing", () => {
  let clock = 0;
  beforeEach(() => {
    clock = 1_000_000;
    resetPollPacing(() => clock);
  });
  afterEach(() => resetPollPacing());

  it("keeps the poller's own pace on a calm server", () => {
    notePollResponse(response(200));
    expect(serverUnderPressure()).toBe(false);
    expect(nextPollDelay(1500)).toBe(1500);
    expect(nextPollDelay(2500, 3)).toBe(2500);
  });

  it("slows to 5 s, backing off to 10 s, after a busy 503", () => {
    notePollError({
      status: 503,
      code: "adaptive_admission_busy",
      details: { retry_after_seconds: 1 },
    });
    expect(serverUnderPressure()).toBe(true);
    expect(nextPollDelay(1500, 0)).toBe(BUSY_MIN_POLL_MS);
    expect(nextPollDelay(1500, 1)).toBe(BUSY_MAX_POLL_MS);
    expect(nextPollDelay(1500, 5)).toBe(BUSY_MAX_POLL_MS);
    // A poller already slower than that keeps its own pace.
    expect(nextPollDelay(15000, 0)).toBe(15000);
  });

  it("honors Retry-After and the server's poll-after hint", () => {
    notePollResponse(response(503, { "Retry-After": "20" }));
    expect(nextPollDelay(1500)).toBe(20_000);
    resetPollPacing(() => clock);
    notePollResponse(response(200, { [POLL_AFTER_HEADER]: "5" }));
    expect(nextPollDelay(1500)).toBe(5000);
    resetPollPacing(() => clock);
    notePollResponse(response(429, { "Retry-After": "600" }));
    expect(nextPollDelay(1500)).toBe(MAX_SERVER_WAIT_MS); // capped
  });

  it("returns to the normal pace once the server stops signalling", () => {
    notePollResponse(response(503));
    expect(nextPollDelay(1500)).toBe(5000);
    clock += PRESSURE_WINDOW_MS + 1;
    expect(serverUnderPressure()).toBe(false);
    expect(nextPollDelay(1500)).toBe(1500);
  });

  it("ignores non-busy errors", () => {
    notePollError({ status: 404, code: "not_found" });
    notePollError(new Error("network"));
    notePollError(null);
    expect(serverUnderPressure()).toBe(false);
  });
});

describe("the API client feeds poll pacing", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    resetPollPacing();
  });

  it("notes the server's poll-after hint on a conversation read", async () => {
    resetPollPacing();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ id: "c1" }), {
          status: 200,
          headers: { [POLL_AFTER_HEADER]: "5" },
        }),
      ),
    );
    const api = new PlatformApi({ baseUrl: "/api/v1" });
    await api.conversationSession("c1");
    expect(serverUnderPressure()).toBe(true);
    expect(nextPollDelay(1500)).toBe(5000);
  });

  it("notes a busy 503 with Retry-After", async () => {
    resetPollPacing();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            code: "adaptive_admission_busy",
            message: "busy",
            details: { retry_after_seconds: 8 },
          }),
          { status: 503, headers: { "Retry-After": "8" } },
        ),
      ),
    );
    const api = new PlatformApi({ baseUrl: "/api/v1" });
    await expect(api.conversationSession("c1")).rejects.toBeTruthy();
    expect(nextPollDelay(1500)).toBe(8000);
  });
});
