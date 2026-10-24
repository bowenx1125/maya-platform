import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useNextAudioPrefetch } from "../components/debate/stage/next-audio-prefetch";

const NEXT_TURN = "22222222-2222-4222-8222-222222222222";
const MEDIA_URL = `/api/v1/debates/11111111-1111-4111-8111-111111111111/audio/${NEXT_TURN}?media_ticket=${"a".repeat(43)}`;

function input(overrides: Record<string, unknown> = {}) {
  return {
    api: {
      prefetchNextDebateAudio: vi
        .fn()
        .mockResolvedValue({ turn_id: NEXT_TURN, media_url: MEDIA_URL }),
    },
    debateId: "11111111-1111-4111-8111-111111111111",
    enabled: true,
    mode: "live",
    status: "playing",
    currentTurnId: "33333333-3333-4333-8333-333333333333",
    controlVersion: 4,
    controllerEpochRef: { current: "44444444-4444-4444-8444-444444444444" },
    nextTurnReady: true,
    ...overrides,
  };
}

describe("next audio prefetch", () => {
  const created = URL.createObjectURL;
  const revoked = URL.revokeObjectURL;
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        blob: async () => new Blob(["RIFF"]),
      }),
    );
    URL.createObjectURL = vi.fn().mockReturnValue("blob:next-turn");
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    URL.createObjectURL = created;
    URL.revokeObjectURL = revoked;
  });

  it("downloads the ready next turn once and plays it from the blob", async () => {
    const props = input();
    const { result, rerender } = renderHook((p) => useNextAudioPrefetch(p), {
      initialProps: props,
    });
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(MEDIA_URL, expect.anything()),
    );
    expect(props.api.prefetchNextDebateAudio).toHaveBeenCalledWith(
      props.debateId,
      {
        expected_control_version: 4,
        expected_current_turn_id: props.currentTurnId,
        controller_epoch: props.controllerEpochRef.current,
      },
    );
    rerender({ ...props, status: "waiting_next" });
    await waitFor(() =>
      expect(result.current.sourceFor(NEXT_TURN, MEDIA_URL)).toBe(
        "blob:next-turn",
      ),
    );
    expect(props.api.prefetchNextDebateAudio).toHaveBeenCalledTimes(1);
  });

  it("falls back to the media URL when the next turn is not ready", async () => {
    const props = input({ nextTurnReady: false });
    const { result } = renderHook(() => useNextAudioPrefetch(props));
    expect(props.api.prefetchNextDebateAudio).not.toHaveBeenCalled();
    expect(result.current.sourceFor(NEXT_TURN, MEDIA_URL)).toBe(MEDIA_URL);
  });

  it("never prefetches for an observer or without a controller", () => {
    for (const overrides of [
      { enabled: false },
      { controllerEpochRef: { current: null } },
      { mode: "replay" },
    ]) {
      const props = input(overrides);
      renderHook(() => useNextAudioPrefetch(props));
      expect(props.api.prefetchNextDebateAudio).not.toHaveBeenCalled();
    }
  });
});
