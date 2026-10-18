/**
 * Shared client cache for page-load reads (Studyform, Brainform, Chatform).
 *
 * - Per API client and per signed-in identity (user id + session generation).
 *   A different identity empties the cache; without a user nothing is cached.
 * - Identical reads in flight are joined; a read under ``FRESH_MS`` old is
 *   reused; an older one (up to ``MAX_STALE_MS``) can be shown at once while
 *   the page refreshes it. Nothing polls from here.
 * - Every mutation sent through ``PlatformApi`` (and any explicit
 *   ``invalidateRequestCache``) empties the cache and stops reads that started
 *   before it from writing back: a late answer never overwrites a newer one.
 * - 401/403/404 and other errors drop the entry. 429/503 (queue full, busy)
 *   start a back-off: reads that have a cached copy keep it and skip the
 *   network until the back-off ends; reads with nothing cached still ask.
 * - At most ``MAX_IN_FLIGHT`` cached reads run at once per API client. Every
 *   read is still an ordinary request through the server's global admission.
 *
 * The server stays the only authority on access: an entry is a copy of one
 * earlier answer to the same identity.
 */

export const FRESH_MS = 10_000;
export const MAX_STALE_MS = 5 * 60_000;
export const MAX_IN_FLIGHT = 6;
const MIN_BACKOFF_MS = 2_000;
const MAX_BACKOFF_MS = 60_000;

type Entry = { value: unknown; at: number };

type Store = {
  identity: string;
  generation: number;
  entries: Map<string, Entry>;
  inflight: Map<string, { promise: Promise<unknown>; generation: number }>;
  coolUntil: number;
  backoffMs: number;
};

type Limiter = { active: number; waiting: Array<() => void> };

const stores = new WeakMap<object, Store>();
const limiters = new WeakMap<object, Limiter>();
const generations = new WeakMap<object, number>();

export function requestCacheIdentity(
  userId: string | null | undefined,
  generation: number | null | undefined,
): string | null {
  return userId ? `${userId}:${generation ?? 0}` : null;
}

function apiGeneration(api: object): number {
  return generations.get(api) ?? 0;
}

function storeFor(api: object, identity: string): Store {
  const current = stores.get(api);
  if (current && current.identity === identity) return current;
  const next: Store = {
    identity,
    generation: apiGeneration(api),
    entries: new Map(),
    inflight: new Map(),
    coolUntil: 0,
    backoffMs: 0,
  };
  stores.set(api, next);
  return next;
}

function currentStore(api: object, identity: string | null): Store | null {
  if (!identity) return null;
  const store = stores.get(api);
  return store && store.identity === identity ? store : null;
}

/** Empty the cache for this client; reads already in flight do not write. */
export function invalidateRequestCache(api: object): void {
  generations.set(api, apiGeneration(api) + 1);
  const store = stores.get(api);
  if (!store) return;
  store.generation = apiGeneration(api);
  store.entries.clear();
  store.inflight.clear();
}

/** The cache's write generation; a page snapshot is kept only if unchanged. */
export function requestCacheGeneration(api: object): number {
  return apiGeneration(api);
}

export function requestKey(name: string, args: readonly unknown[]): string {
  return `${name}:${JSON.stringify(args)}`;
}

function statusOf(cause: unknown): number | undefined {
  if (cause && typeof cause === "object" && "status" in cause) {
    const status = (cause as { status: unknown }).status;
    return typeof status === "number" ? status : undefined;
  }
  return undefined;
}

/** 429 or 503: the server's queue is full or it is shedding load. */
export function isBusyResponse(cause: unknown): boolean {
  const status = statusOf(cause);
  return status === 429 || status === 503;
}

function retryAfterMs(cause: unknown): number | undefined {
  if (!cause || typeof cause !== "object" || !("details" in cause))
    return undefined;
  const details = (cause as { details?: Record<string, unknown> }).details;
  const seconds = details?.retry_after_seconds;
  return typeof seconds === "number" && Number.isFinite(seconds) && seconds > 0
    ? seconds * 1000
    : undefined;
}

function limited<T>(api: object, run: () => Promise<T>): Promise<T> {
  let limiter = limiters.get(api);
  if (!limiter) {
    limiter = { active: 0, waiting: [] };
    limiters.set(api, limiter);
  }
  const slot = limiter;
  const start = () => {
    slot.active += 1;
    let result: Promise<T>;
    try {
      result = run();
    } catch (cause) {
      result = Promise.reject(cause);
    }
    const release = () => {
      slot.active -= 1;
      slot.waiting.shift()?.();
    };
    result.then(release, release);
    return result;
  };
  if (slot.active < MAX_IN_FLIGHT) return start();
  return new Promise<T>((resolve, reject) => {
    slot.waiting.push(() => {
      start().then(resolve, reject);
    });
  });
}

/** A cached copy younger than ``MAX_STALE_MS``, for an instant first paint. */
export function peekRequestCache<T>(
  api: object,
  identity: string | null,
  key: string,
): T | undefined {
  const store = currentStore(api, identity);
  const entry = store?.entries.get(key);
  if (!entry || Date.now() - entry.at > MAX_STALE_MS) return undefined;
  return entry.value as T;
}

/**
 * Keep a page snapshot assembled from reads that began at ``generation``.
 * A mutation since then (or a different identity) discards it.
 */
export function rememberRequestCache(
  api: object,
  identity: string | null,
  key: string,
  value: unknown,
  generation: number,
): void {
  if (!identity || generation !== apiGeneration(api)) return;
  storeFor(api, identity).entries.set(key, { value, at: Date.now() });
}

export function forgetRequestCache(
  api: object,
  identity: string | null,
  key: string,
): void {
  currentStore(api, identity)?.entries.delete(key);
}

/**
 * One cached read. ``refresh`` skips the fresh copy and the in-flight join
 * (a page's background refresh); it still honours a busy back-off when a
 * cached copy exists.
 */
export function cachedRequest<T>(
  api: object,
  identity: string | null,
  key: string,
  fetcher: () => Promise<T>,
  { refresh = false }: { refresh?: boolean } = {},
): Promise<T> {
  if (!identity) return limited(api, fetcher);
  const store = storeFor(api, identity);
  const entry = store.entries.get(key);
  const now = Date.now();
  const usable = entry && now - entry.at <= MAX_STALE_MS ? entry : undefined;
  if (!refresh) {
    const pending = store.inflight.get(key);
    if (pending && pending.generation === store.generation)
      return pending.promise as Promise<T>;
    if (usable && now - usable.at < FRESH_MS)
      return Promise.resolve(usable.value as T);
  }
  if (usable && now < store.coolUntil)
    return Promise.resolve(usable.value as T);
  const generation = store.generation;
  const owns = () =>
    stores.get(api) === store &&
    store.generation === generation &&
    store.inflight.get(key)?.promise === promise;
  const promise: Promise<T> = limited(api, fetcher).then(
    (value) => {
      if (owns()) {
        store.entries.set(key, { value, at: Date.now() });
        store.backoffMs = 0;
      }
      return value;
    },
    (cause: unknown) => {
      if (isBusyResponse(cause)) {
        if (stores.get(api) === store) {
          store.backoffMs = Math.min(
            MAX_BACKOFF_MS,
            Math.max(MIN_BACKOFF_MS, store.backoffMs * 2),
          );
          store.coolUntil =
            Date.now() + (retryAfterMs(cause) ?? store.backoffMs);
        }
        // Keep showing the copy we have instead of an error.
        const kept = owns() ? usable : undefined;
        if (kept) return kept.value as T;
      } else if (owns()) {
        store.entries.delete(key);
      }
      throw cause;
    },
  );
  store.inflight.set(key, { promise, generation });
  const settle = () => {
    if (store.inflight.get(key)?.promise === promise)
      store.inflight.delete(key);
  };
  promise.then(settle, settle);
  return promise;
}

/** Shorthand: ``cachedCall(api, id, "group", [groupId], () => api.group(groupId))``. */
export function cachedCall<T>(
  api: object,
  identity: string | null,
  name: string,
  args: readonly unknown[],
  fetcher: () => Promise<T>,
  options?: { refresh?: boolean },
): Promise<T> {
  return cachedRequest(api, identity, requestKey(name, args), fetcher, options);
}
