import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useImmerseAudioQueue } from "../components/debate/stage/next-audio-prefetch";

const DEBATE = "11111111-1111-4111-8111-111111111111";
const EPOCH = "44444444-4444-4444-8444-444444444444";
const TURNS = [
  "21111111-1111-4111-8111-111111111111",
  "22222222-2222-4222-8222-222222222222",
  "23333333-3333-4333-8333-333333333333",
  "24444444-4444-4444-8444-444444444444",
];
const mediaUrl = (turnId: string) =>
  `/api/v1/debates/${DEBATE}/audio/${turnId}?media_ticket=${"a".repeat(43)}`;

type Deferred = { resolve: () => void; signal: AbortSignal };

describe("Immerse audio queue (PR A2)", () => {
  const created = URL.createObjectURL;
  const revoked = URL.revokeObjectURL;
  let downloads: Map<string, Deferred>;
  let order: string[];

  beforeEach(() => {
    downloads = new Map();
    order = [];
    // Each download stays open until the test lets it finish, so "one at a
    // time" is observable.
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (url: string, init: RequestInit) =>
          new Promise((resolve, reject) => {
            const turnId = TURNS.find((turn) => url.includes(turn)) ?? url;
            order.push(turnId);
            const signal = init.signal as AbortSignal;
            signal.addEventListener("abort", () =>
              reject(new DOMException("aborted", "AbortError")),
            );
            downloads.set(turnId, {
              signal,
              resolve: () =>
                resolve({
                  ok: true,
                  status: 200,
                  blob: async () => new Blob(["RIFF"]),
                }),
            });
          }),
      ),
    );
    URL.createObjectURL = vi.fn(() => `blob:${order[order.length - 1]}`);
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    URL.createObjectURL = created;
    URL.revokeObjectURL = revoked;
  });

  function setup() {
    const api = {
      prefetchNextDebateAudio: vi.fn(
        async (_debateId: string, body: { turn_id?: string | null }) => ({
          turn_id: body.turn_id as string,
          media_url: mediaUrl(body.turn_id as string),
        }),
      ),
    };
    const props = {
      api,
      debateId: DEBATE,
      enabled: true,
      controllerEpochRef: { current: EPOCH },
      controllerReady: true,
      sceneSettled: false,
      started: false,
    };
    const hook = renderHook((p) => useImmerseAudioQueue(p), {
      initialProps: props,
    });
    return { api, props, hook };
  }

  async function finish(turnId: string) {
    await waitFor(() => expect(downloads.has(turnId)).toBe(true));
    await act(async () => downloads.get(turnId)!.resolve());
  }

  it("downloads ready speeches in order after the scene, uses the blob on Next, and frees all on exit", async () => {
    const { api, props, hook } = setup();
    // Entering Immerse: the snapshot lists two ready speeches.
    act(() => hook.result.current.noteReady([TURNS[0], TURNS[1]]));
    // Nothing competes with the 3D scene while it loads.
    expect(fetch).not.toHaveBeenCalled();
    hook.rerender({ ...props, sceneSettled: true });

    // One at a time, in speaking order: the second waits for the first.
    await waitFor(() => expect(downloads.has(TURNS[0])).toBe(true));
    expect(order).toEqual([TURNS[0]]);
    await finish(TURNS[0]);
    await waitFor(() => expect(downloads.has(TURNS[1])).toBe(true));
    expect(order).toEqual([TURNS[0], TURNS[1]]);
    await finish(TURNS[1]);
    expect(api.prefetchNextDebateAudio).toHaveBeenCalledWith(DEBATE, {
      controller_epoch: EPOCH,
      turn_id: TURNS[0],
    });

    // turn.audio_ready: the next speech is generated later and joins the queue.
    act(() => hook.result.current.noteReady([TURNS[2]]));
    await finish(TURNS[2]);

    // Next: the speech plays from its blob and nothing is downloaded again.
    const requestsBeforeNext = (fetch as ReturnType<typeof vi.fn>).mock.calls
      .length;
    await expect(
      hook.result.current.sourceFor(TURNS[1], mediaUrl(TURNS[1])),
    ).resolves.toBe(`blob:${TURNS[1]}`);
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(
      requestsBeforeNext,
    );

    // A fourth speech is still downloading when the teacher leaves Immerse.
    act(() => hook.result.current.noteReady([TURNS[3]]));
    await waitFor(() => expect(downloads.has(TURNS[3])).toBe(true));
    hook.unmount();
    expect(downloads.get(TURNS[3])!.signal.aborted).toBe(true);
    for (const turnId of TURNS.slice(0, 3)) {
      expect(URL.revokeObjectURL).toHaveBeenCalledWith(`blob:${turnId}`);
    }
    const afterExit = (fetch as ReturnType<typeof vi.fn>).mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(
      afterExit,
    );
  });
});
