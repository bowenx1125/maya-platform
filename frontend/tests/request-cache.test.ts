import { afterEach, describe, expect, it, vi } from "vitest";

import { PlatformApi, PlatformApiError } from "../lib/api/platform";
import {
  cachedCall,
  FRESH_MS,
  invalidateRequestCache,
  MAX_IN_FLIGHT,
  peekRequestCache,
  rememberRequestCache,
  requestCacheGeneration,
  requestCacheIdentity,
  requestKey,
} from "../lib/request-cache";

const A = requestCacheIdentity("user-a", 1);
const B = requestCacheIdentity("user-b", 1);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (cause: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function later(ms: number) {
  const now = Date.now() + ms;
  vi.spyOn(Date, "now").mockReturnValue(now);
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("shared page-load request cache", () => {
  it("sends identical reads in flight once and keeps different reads apart", async () => {
    const api = {};
    const run = vi.fn(async () => ["x"]);
    const [first, second, other] = await Promise.all([
      cachedCall(api, A, "teams", ["c1"], run),
      cachedCall(api, A, "teams", ["c1"], run),
      cachedCall(api, A, "teams", ["c2"], run),
    ]);
    expect(first).toBe(second);
    expect(other).toEqual(["x"]);
    expect(run).toHaveBeenCalledTimes(2);
  });

  it("reuses a fresh read and asks again once it is older than FRESH_MS", async () => {
    const api = {};
    const run = vi.fn().mockResolvedValueOnce(1).mockResolvedValueOnce(2);
    expect(await cachedCall(api, A, "x", [], run)).toBe(1);
    expect(await cachedCall(api, A, "x", [], run)).toBe(1);
    later(FRESH_MS + 1);
    expect(await cachedCall(api, A, "x", [], run)).toBe(2);
    expect(run).toHaveBeenCalledTimes(2);
  });

  it("refresh asks the server even for a fresh read", async () => {
    const api = {};
    const run = vi.fn().mockResolvedValueOnce(1).mockResolvedValueOnce(2);
    await cachedCall(api, A, "x", [], run);
    expect(await cachedCall(api, A, "x", [], run, { refresh: true })).toBe(2);
  });

  it("never shares across identities and caches nothing without one", async () => {
    const api = {};
    await cachedCall(api, A, "x", [], async () => "a-only");
    expect(peekRequestCache(api, B, requestKey("x", []))).toBeUndefined();
    const run = vi.fn(async () => "b");
    expect(await cachedCall(api, B, "x", [], run)).toBe("b");
    // Switching identity emptied A's entries.
    expect(peekRequestCache(api, A, requestKey("x", []))).toBeUndefined();
    const anon = vi.fn(async () => "anon");
    await cachedCall(api, null, "x", [], anon);
    await cachedCall(api, null, "x", [], anon);
    expect(anon).toHaveBeenCalledTimes(2);
  });

  it("a read that began before a change never writes after it", async () => {
    const api = {};
    const stale = deferred<string>();
    const early = cachedCall(api, A, "x", [], () => stale.promise);
    invalidateRequestCache(api);
    const fresh = vi.fn(async () => "after");
    expect(await cachedCall(api, A, "x", [], fresh)).toBe("after");
    stale.resolve("before");
    expect(await early).toBe("before");
    expect(peekRequestCache(api, A, requestKey("x", []))).toBe("after");
    expect(fresh).toHaveBeenCalledTimes(1);
  });

  it("a page snapshot is kept only if nothing changed since its reads began", () => {
    const api = {};
    const generation = requestCacheGeneration(api);
    invalidateRequestCache(api);
    rememberRequestCache(api, A, "page", { stale: true }, generation);
    expect(peekRequestCache(api, A, "page")).toBeUndefined();
    rememberRequestCache(
      api,
      A,
      "page",
      { ok: true },
      requestCacheGeneration(api),
    );
    expect(peekRequestCache(api, A, "page")).toEqual({ ok: true });
  });

  it("a refusal drops the cached read", async () => {
    const api = {};
    await cachedCall(api, A, "group", ["g"], async () => "visible");
    later(FRESH_MS + 1);
    await expect(
      cachedCall(api, A, "group", ["g"], async () => {
        throw new PlatformApiError(403, "no");
      }),
    ).rejects.toThrow("no");
    expect(peekRequestCache(api, A, requestKey("group", ["g"]))).toBe(
      undefined,
    );
  });

  it("a busy server keeps the cached copy and backs off before asking again", async () => {
    const api = {};
    await cachedCall(api, A, "x", [], async () => "cached");
    later(FRESH_MS + 1);
    const busy = vi.fn(async () => {
      throw new PlatformApiError(429, "busy", {
        code: "queue_full",
        details: { retry_after_seconds: 5 },
      });
    });
    expect(await cachedCall(api, A, "x", [], busy, { refresh: true })).toBe(
      "cached",
    );
    // Inside the back-off: no request at all, the copy is shown.
    const during = vi.fn(async () => "new");
    expect(await cachedCall(api, A, "x", [], during, { refresh: true })).toBe(
      "cached",
    );
    expect(during).not.toHaveBeenCalled();
    // After Retry-After the next refresh asks again.
    vi.restoreAllMocks();
    later(FRESH_MS + 6_000);
    expect(await cachedCall(api, A, "x", [], during, { refresh: true })).toBe(
      "new",
    );
  });

  it("a busy answer with nothing cached is still an error", async () => {
    const api = {};
    await expect(
      cachedCall(api, A, "x", [], async () => {
        throw new PlatformApiError(503, "shedding");
      }),
    ).rejects.toThrow("shedding");
  });

  it(`runs at most ${MAX_IN_FLIGHT} cached reads at once per client`, async () => {
    const api = {};
    let active = 0;
    let peak = 0;
    const gates = Array.from({ length: 10 }, () => deferred<number>());
    const reads = gates.map((gate, index) =>
      cachedCall(api, A, "r", [index], () => {
        active += 1;
        peak = Math.max(peak, active);
        return gate.promise.finally(() => {
          active -= 1;
        });
      }),
    );
    await Promise.resolve();
    expect(active).toBe(MAX_IN_FLIGHT);
    gates.forEach((gate, index) => gate.resolve(index));
    expect(await Promise.all(reads)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
    expect(peak).toBe(MAX_IN_FLIGHT);
  });

  it("every PlatformApi change empties the cache, generated or hand-written", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(null, {
          status: 204,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const api = new PlatformApi({ baseUrl: "http://maya.test/api/v1" });
    await cachedCall(api, A, "teams", ["c"], async () => ["t"]);
    expect(peekRequestCache(api, A, requestKey("teams", ["c"]))).toEqual(["t"]);
    await api.deleteTeam("team-1").catch(() => undefined);
    expect(fetchMock).toHaveBeenCalled();
    expect(peekRequestCache(api, A, requestKey("teams", ["c"]))).toBe(
      undefined,
    );

    // Hand-written fetch path (POST /conversations).
    await cachedCall(api, A, "teams", ["c"], async () => ["t2"]);
    await api.createConversation("version-1").catch(() => undefined);
    expect(peekRequestCache(api, A, requestKey("teams", ["c"]))).toBe(
      undefined,
    );
  });
});
