import type { VoiceProfile } from "./api";
import {
  FRESH_MS,
  cachedRequest,
  forgetRequestCache,
  peekRequestCache,
  requestCacheIdentity,
} from "./request-cache";

/**
 * Studyform voice lists, kept in the shared page-load cache
 * (``request-cache.ts``) so there is one client cache, not two.
 *
 * A return visit shows this sign-in's last list at once and refreshes it in
 * the background. The server stays the only authority on who sees which
 * voice: an entry is a copy of one earlier answer to the same identity, every
 * mutation empties the cache, and each list read is an ordinary request
 * through the server's global admission.
 */

export type VoiceListKind = "group" | "personal";

type VoiceListApi = {
  voiceProfiles(groupId: string): Promise<VoiceProfile[]>;
  personalVoiceProfiles?(courseId: string): Promise<VoiceProfile[]>;
};

/** A list this young is the answer: a prefetch that just landed is not asked
 * for again when the panel mounts. Older lists show at once and refresh. */
export const VOICE_LIST_FRESH_MS = FRESH_MS;

export const voiceListIdentity = requestCacheIdentity;

function listKey(kind: VoiceListKind, scopeId: string): string {
  return `voices:${kind}:${scopeId}`;
}

export function cachedVoiceList(
  api: object,
  identity: string | null,
  kind: VoiceListKind,
  scopeId: string,
): VoiceProfile[] | undefined {
  return peekRequestCache<VoiceProfile[]>(
    api,
    identity,
    listKey(kind, scopeId),
  );
}

/** Forget one list after a change made without reloading it (a rename). */
export function forgetVoiceList(
  api: object,
  identity: string | null,
  kind: VoiceListKind,
  scopeId: string,
): void {
  forgetRequestCache(api, identity, listKey(kind, scopeId));
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
  return cachedRequest(
    api,
    identity,
    listKey(kind, scopeId),
    () =>
      kind === "personal"
        ? api.personalVoiceProfiles!(scopeId)
        : api.voiceProfiles(scopeId),
    { refresh: !reuse },
  );
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
