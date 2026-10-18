import type { VoiceProfile } from "./api";

/**
 * Last voice list the server returned to this signed-in person, so Studyform
 * shows it at once on a return visit and refreshes it in the background.
 *
 * The server stays the only authority on who sees which voice: an entry is a
 * copy of one earlier answer to the same person, it is replaced by the next
 * answer, and every mutation reloads from the server. Entries belong to one
 * identity (user id plus session generation); a different identity empties
 * the cache, and without a known user nothing is cached at all.
 */

export type VoiceListKind = "group" | "personal";

type VoiceListApi = {
  voiceProfiles(groupId: string): Promise<VoiceProfile[]>;
  personalVoiceProfiles?(courseId: string): Promise<VoiceProfile[]>;
};

type CachedList = { profiles: VoiceProfile[]; fetchedAt: number };

type IdentityCache = {
  identity: string;
  lists: Map<string, CachedList>;
  inflight: Map<string, Promise<VoiceProfile[]>>;
};

/** A list this young is the answer: a prefetch that just landed is not asked
 * for again when the panel mounts. Older lists show at once and refresh. */
export const VOICE_LIST_FRESH_MS = 10_000;

// Keyed by the API client, so separate clients (and test doubles) never share.
const caches = new WeakMap<object, IdentityCache>();

export function voiceListIdentity(
  userId: string | null | undefined,
  generation: number | null | undefined,
): string | null {
  return userId ? `${userId}:${generation ?? 0}` : null;
}

function cacheFor(api: object, identity: string): IdentityCache {
  const current = caches.get(api);
  if (current && current.identity === identity) return current;
  const next: IdentityCache = {
    identity,
    lists: new Map(),
    inflight: new Map(),
  };
  caches.set(api, next);
  return next;
}

function listKey(kind: VoiceListKind, scopeId: string): string {
  return `${kind}:${scopeId}`;
}

export function cachedVoiceList(
  api: object,
  identity: string | null,
  kind: VoiceListKind,
  scopeId: string,
): VoiceProfile[] | undefined {
  if (!identity) return undefined;
  const current = caches.get(api);
  if (!current || current.identity !== identity) return undefined;
  return current.lists.get(listKey(kind, scopeId))?.profiles;
}

/** Forget one list after a change made without reloading it (a rename). */
export function forgetVoiceList(
  api: object,
  identity: string | null,
  kind: VoiceListKind,
  scopeId: string,
): void {
  if (!identity) return;
  const current = caches.get(api);
  if (!current || current.identity !== identity) return;
  current.lists.delete(listKey(kind, scopeId));
}

/**
 * Fetch one voice list and remember a successful answer.
 *
 * ``reuse`` joins a request already in flight (a Studyform prefetch) or takes
 * a list fetched within ``VOICE_LIST_FRESH_MS``. Every other load, including
 * a reload after a mutation, asks the server and never adopts an answer that
 * started before the change.
 */
export function fetchVoiceList(
  api: VoiceListApi,
  identity: string | null,
  kind: VoiceListKind,
  scopeId: string,
  { reuse = false }: { reuse?: boolean } = {},
): Promise<VoiceProfile[]> {
  const request = () =>
    kind === "personal"
      ? api.personalVoiceProfiles!(scopeId)
      : api.voiceProfiles(scopeId);
  if (!identity) return request();
  const cache = cacheFor(api, identity);
  const key = listKey(kind, scopeId);
  if (reuse) {
    const pending = cache.inflight.get(key);
    if (pending) return pending;
    const recent = cache.lists.get(key);
    if (recent && Date.now() - recent.fetchedAt < VOICE_LIST_FRESH_MS)
      return Promise.resolve(recent.profiles);
  }
  const promise = request().then(
    (profiles) => {
      // A newer request for this list owns the cache; a late one never wins.
      if (caches.get(api) === cache && cache.inflight.get(key) === promise) {
        cache.lists.set(key, { profiles, fetchedAt: Date.now() });
      }
      return profiles;
    },
    (cause: unknown) => {
      // A refusal or outage is not a list: forget what this person saw.
      if (caches.get(api) === cache && cache.inflight.get(key) === promise) {
        cache.lists.delete(key);
      }
      throw cause;
    },
  );
  cache.inflight.set(key, promise);
  const settle = () => {
    if (cache.inflight.get(key) === promise) cache.inflight.delete(key);
  };
  promise.then(settle, settle);
  return promise;
}

/** Start loading a voice list early; the panel joins it when it mounts. */
export function prefetchVoiceList(
  api: VoiceListApi,
  identity: string | null,
  kind: VoiceListKind,
  scopeId: string | null | undefined,
): void {
  if (!identity || !scopeId) return;
  if (kind === "personal" && typeof api.personalVoiceProfiles !== "function")
    return;
  if (typeof api.voiceProfiles !== "function" && kind === "group") return;
  void fetchVoiceList(api, identity, kind, scopeId, { reuse: true }).catch(
    () => undefined,
  );
}
