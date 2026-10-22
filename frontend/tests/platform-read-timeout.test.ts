import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformApi } from "../lib/api/platform";
import { cachedCall } from "../lib/request-cache";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const reads = [
  ["courses", (api: PlatformApi) => api.courses()],
  ["groups", (api: PlatformApi) => api.groups("course-1")],
  ["group", (api: PlatformApi) => api.group("group-1")],
  ["knowledge", (api: PlatformApi) => api.knowledge("group-1")],
  ["chatAgents", (api: PlatformApi) => api.chatAgents("course-1")],
  [
    "brainformKnowledge",
    (api: PlatformApi) => api.brainformKnowledge("course-1"),
  ],
  [
    "workspaceDocuments",
    (api: PlatformApi) => api.workspaceDocuments("course-1"),
  ],
] as const;

describe("workspace read deadlines", () => {
  it.each(reads)(
    "aborts a stalled %s fetch after 60 seconds",
    async (_name, read) => {
      let signal!: AbortSignal;
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockImplementation((input, init) => {
          signal = new Request(input, init).signal;
          return new Promise((_resolve, reject) => {
            signal.addEventListener("abort", () => reject(signal.reason), {
              once: true,
            });
          });
        });
      const api = new PlatformApi({ baseUrl: "http://maya.test/api/v1" });
      const result = read(api).catch((cause: unknown) => cause);
      await vi.advanceTimersByTimeAsync(59_999);
      expect(signal.aborted).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      expect(signal.aborted).toBe(true);
      expect(await result).toMatchObject({ name: "AbortError" });
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it.each([reads[0], reads[5]])(
    "also aborts a stalled %s response body",
    async (_name, read) => {
      let signal!: AbortSignal;
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
        signal = new Request(input, init).signal;
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            signal.addEventListener(
              "abort",
              () => controller.error(signal.reason),
              { once: true },
            );
          },
        });
        return new Response(body, {
          headers: { "Content-Type": "application/json" },
        });
      });
      const api = new PlatformApi({ baseUrl: "http://maya.test/api/v1" });
      const result = read(api).catch((cause: unknown) => cause);
      await vi.advanceTimersByTimeAsync(60_000);
      expect(signal.aborted).toBe(true);
      expect(await result).toMatchObject({ name: "AbortError" });
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it("joins pending reads and releases their cache slot on abort before retrying", async () => {
    const signals: AbortSignal[] = [];
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input, init) => {
        const signal = new Request(input, init).signal;
        signals.push(signal);
        if (signals.length > 1) return Promise.resolve(new Response("[]"));
        return new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason), {
            once: true,
          });
        });
      });
    const api = new PlatformApi({ baseUrl: "http://maya.test/api/v1" });
    const read = () =>
      cachedCall(api, "teacher-one:1", "courses", [], () => api.courses());
    const first = read();
    expect(read()).toBe(first);
    const result = first.catch((cause: unknown) => cause);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(await result).toMatchObject({ name: "AbortError" });
    expect(signals[0].aborted).toBe(true);
    expect(await read()).toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(signals[1].aborted).toBe(false);
  });
});
