import { describe, expect, it, vi } from "vitest";

import {
  previewTurnInFlight,
  previewTurnReady,
  retryPreviewTurnsInOrder,
  type PreviewRetrySnapshot,
  type PreviewRetryTurn,
} from "../lib/retry-preview-turns";

function turn(
  id: string,
  status: string,
  extra: Partial<PreviewRetryTurn> = {},
): PreviewRetryTurn {
  return {
    id,
    generation_status: status,
    speech: extra.speech ?? (status === "final_ready" ? "Saved speech." : ""),
    audio_ready: extra.audio_ready ?? status === "final_ready",
    safe_error_code: extra.safe_error_code ?? null,
    ...extra,
  };
}

function snapshot(
  version: number,
  turns: PreviewRetryTurn[],
): PreviewRetrySnapshot {
  return { playback: { control_version: version }, preview_turns: turns };
}

describe("retryPreviewTurnsInOrder", () => {
  it("treats saved final_ready speech as ready and pending as in flight", () => {
    expect(
      previewTurnReady(turn("a", "final_ready", { speech: "Hello." })),
    ).toBe(true);
    expect(previewTurnReady(turn("a", "pending"))).toBe(false);
    expect(previewTurnInFlight(turn("a", "pending"))).toBe(true);
    expect(
      previewTurnInFlight(
        turn("a", "failed", { safe_error_code: "preparation_timeout" }),
      ),
    ).toBe(false);
  });

  it("retries later failed turns only after the earlier turn is ready", async () => {
    const states = [
      snapshot(2, [
        turn("turn-4", "pending"),
        turn("turn-5", "failed", { safe_error_code: "preparation_timeout" }),
        turn("turn-6", "failed", { safe_error_code: "preparation_timeout" }),
      ]),
      snapshot(2, [
        turn("turn-4", "final_ready"),
        turn("turn-5", "failed", { safe_error_code: "preparation_timeout" }),
        turn("turn-6", "failed", { safe_error_code: "preparation_timeout" }),
      ]),
      snapshot(3, [
        turn("turn-4", "final_ready"),
        turn("turn-5", "pending"),
        turn("turn-6", "failed", { safe_error_code: "preparation_timeout" }),
      ]),
      snapshot(3, [
        turn("turn-4", "final_ready"),
        turn("turn-5", "final_ready"),
        turn("turn-6", "failed", { safe_error_code: "preparation_timeout" }),
      ]),
      snapshot(4, [
        turn("turn-4", "final_ready"),
        turn("turn-5", "final_ready"),
        turn("turn-6", "pending"),
      ]),
      snapshot(4, [
        turn("turn-4", "final_ready"),
        turn("turn-5", "final_ready"),
        turn("turn-6", "final_ready"),
      ]),
    ];
    const retry = vi.fn(async () => undefined);
    const refresh = vi.fn(async () => {
      const next = states.shift();
      if (!next) throw new Error("unexpected extra refresh");
      return next;
    });

    const result = await retryPreviewTurnsInOrder({
      turnIds: ["turn-4", "turn-5", "turn-6"],
      controlVersion: 1,
      retry,
      refresh,
      delay: async () => undefined,
    });

    expect(retry.mock.calls.map((call) => call[0])).toEqual([
      "turn-4",
      "turn-5",
      "turn-6",
    ]);
    expect(retry.mock.calls.map((call) => call[1])).toEqual([1, 2, 3]);
    expect(result).toEqual({ controlVersion: 4 });
  });

  it("does not submit the next turn while the current one is still preparing", async () => {
    const retry = vi.fn(async () => undefined);
    const refresh = vi.fn(async () =>
      snapshot(2, [
        turn("turn-4", "pending"),
        turn("turn-5", "failed", { safe_error_code: "preparation_timeout" }),
      ]),
    );

    const result = await retryPreviewTurnsInOrder({
      turnIds: ["turn-4", "turn-5"],
      controlVersion: 1,
      retry,
      refresh,
      delay: async () => undefined,
      timeoutMs: 0,
      now: () => 0,
    });

    expect(retry).toHaveBeenCalledTimes(1);
    expect(retry).toHaveBeenCalledWith("turn-4", 1);
    expect(result).toEqual({ controlVersion: 2, timedOutTurnId: "turn-4" });
  });

  it("stops the chain if a retried turn fails again after leaving flight", async () => {
    const states = [
      snapshot(2, [turn("turn-4", "pending")]),
      snapshot(2, [
        turn("turn-4", "failed", { safe_error_code: "turn_generation_failed" }),
      ]),
    ];
    const retry = vi.fn(async () => undefined);
    const refresh = vi.fn(async () => states.shift()!);

    const result = await retryPreviewTurnsInOrder({
      turnIds: ["turn-4", "turn-5"],
      controlVersion: 1,
      retry,
      refresh,
      delay: async () => undefined,
    });

    expect(retry).toHaveBeenCalledTimes(1);
    expect(result).toEqual({ controlVersion: 2, failedTurnId: "turn-4" });
  });

  it("ignores a stale failed snapshot until the retried turn is seen in flight", async () => {
    const states = [
      snapshot(2, [
        turn("turn-4", "failed", { safe_error_code: "preparation_timeout" }),
      ]),
      snapshot(2, [turn("turn-4", "pending")]),
      snapshot(2, [turn("turn-4", "final_ready")]),
    ];
    const retry = vi.fn(async () => undefined);
    const refresh = vi.fn(async () => states.shift()!);

    const result = await retryPreviewTurnsInOrder({
      turnIds: ["turn-4"],
      controlVersion: 1,
      retry,
      refresh,
      delay: async () => undefined,
    });

    expect(retry).toHaveBeenCalledTimes(1);
    expect(result).toEqual({ controlVersion: 2 });
  });
});
