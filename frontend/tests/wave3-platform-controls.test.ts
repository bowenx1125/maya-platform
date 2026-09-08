import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createIdempotencyHandle,
  PlatformApi,
  type DebateDetail,
  type DebatePlaybackState,
} from "../lib/api";

const debateId = "20000000-0000-4000-8000-000000000001";

const playback: DebatePlaybackState = {
  status: "paused",
  mode: "live",
  current_turn_id: "40000000-0000-4000-8000-000000000001",
  cursor_ms: 120,
  playback_rate: 1,
  control_version: 3,
  next_turn_ready: false,
};

const detail = {
  id: debateId,
  course_id: "10000000-0000-4000-8000-000000000001",
  topic: "Should classrooms compare cultural perspectives?",
  background: "",
  status: "stopped",
  created_at: "2026-08-30T00:00:00Z",
  audio_restore_needed: false,
  prepared_turns: 0,
  expected_turns: 0,
  preview: null,
  output_language: "en",
  turn_protocol: null,
  preview_turns: [],
  final_input_frozen: false,
  stall: null,
  revision: 1,
  last_sequence: 3,
  rule_set_id: "ordered_multi_agent_rounds_demo_v1",
  round_count: 2,
  participants: [],
  public_turns: [],
  playback: { ...playback, status: "stopped", current_turn_id: null },
  interaction_status: "closed",
  insight_status: "not_started",
  report_status: "not_started",
} as DebateDetail;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Wave 3 concrete PlatformApi controls", () => {
  it("calls pause, resume and finish through the frozen platform routes", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const request =
          input instanceof Request ? input : new Request(input, init);
        const url = request.url;
        calls.push({ url, init: { headers: request.headers } });
        const body = url.endsWith("/finish")
          ? detail
          : {
              ...playback,
              status: url.endsWith("/resume") ? "ready" : "paused",
            };
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    const api = new PlatformApi({
      baseUrl: "http://maya.test/api/v1",
      csrfToken: "c".repeat(32),
    });
    await api.pauseDebate(
      debateId,
      { expected_control_version: 2 },
      { idempotency: createIdempotencyHandle() },
    );
    await api.resumeDebate(
      debateId,
      { expected_control_version: 3 },
      { idempotency: createIdempotencyHandle() },
    );
    await api.finishDebate(
      debateId,
      {
        expected_control_version: 4,
        expected_current_turn_id: playback.current_turn_id,
      },
      { idempotency: createIdempotencyHandle() },
    );

    expect(calls.map((call) => call.url)).toEqual([
      `http://maya.test/api/v1/debates/${debateId}/pause`,
      `http://maya.test/api/v1/debates/${debateId}/resume`,
      `http://maya.test/api/v1/debates/${debateId}/finish`,
    ]);
    for (const call of calls) {
      const headers = new Headers(call.init?.headers);
      expect(headers.get("X-CSRF-Token")).toBe("c".repeat(32));
      expect(headers.get("Idempotency-Key")?.length).toBeGreaterThanOrEqual(16);
    }
  });
});
