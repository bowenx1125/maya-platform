import type { ChatSession } from "./api";

/**
 * Survives AgentChat unmount so a reply in flight keeps its spinner and
 * lands in the thread when the user navigates back without a manual refresh.
 */
export type ChatRequestState = {
  scopeKey: string | null;
  attemptId: number;
  sessionId: string | null;
  versionId: string;
  message: string;
  requestId: string;
  revision: number;
  /** Null after uncertain transport so a retry can reopen the same request_id. */
  promise: Promise<ChatSession> | null;
  status: "in_flight" | "uncertain" | "observing";
  observedTurnId?: string;
};

export type NewChatRequestState = Omit<
  ChatRequestState,
  "attemptId" | "scopeKey" | "status"
> & { attemptId?: number; scopeKey?: string | null };

type Listener = { callback: () => void; scopeKey?: string | null };

let current: ChatRequestState | null = null;
let settled: ChatSession | null = null;
let activeScopeKey: string | null = null;
let attemptSequence = 0;
const listeners = new Set<Listener>();

function emit() {
  for (const listener of listeners) {
    if (
      listener.scopeKey === undefined ||
      listener.scopeKey === activeScopeKey
    ) {
      listener.callback();
    }
  }
}

function scopeMatches(scopeKey?: string | null): boolean {
  return scopeKey === undefined || scopeKey === activeScopeKey;
}

export function isChatRequestScopeActive(scopeKey: string | null): boolean {
  return scopeKey === activeScopeKey;
}

export function resetChatRequestIdentity() {
  activeScopeKey = null;
  current = null;
  settled = null;
  attemptSequence += 1;
  emit();
}

export function setChatRequestScope(scopeKey: string) {
  if (activeScopeKey === scopeKey) return;
  activeScopeKey = scopeKey;
  current = null;
  settled = null;
  attemptSequence += 1;
  emit();
}

export function createChatRequestAttempt(
  scopeKey?: string | null,
): number | null {
  if (!scopeMatches(scopeKey)) return null;
  attemptSequence += 1;
  return attemptSequence;
}

export function isChatRequestAttemptCurrent(
  attemptId: number,
  scopeKey: string | null,
): boolean {
  return scopeMatches(scopeKey) && attemptSequence === attemptId;
}

export function getChatRequest(
  scopeKey?: string | null,
): ChatRequestState | null {
  if (!scopeMatches(scopeKey)) return null;
  return current?.scopeKey === activeScopeKey ? current : null;
}

export function getSettledChatSession(
  scopeKey?: string | null,
): ChatSession | null {
  if (!scopeMatches(scopeKey)) return null;
  return settled;
}

export function clearSettledChatSession(scopeKey?: string | null) {
  if (!scopeMatches(scopeKey)) return;
  settled = null;
}

export function settleChatRequest(
  requestId: string,
  session: ChatSession | null,
  scopeKey?: string | null,
  attemptId?: number,
) {
  if (
    !scopeMatches(scopeKey) ||
    current?.scopeKey !== activeScopeKey ||
    current?.requestId !== requestId ||
    (attemptId !== undefined && current.attemptId !== attemptId)
  ) {
    return;
  }
  settled = session;
  current = null;
  emit();
}

export function observeChatRequestOnTurn(
  requestId: string,
  observedTurnId: string,
  scopeKey?: string | null,
  attemptId?: number,
) {
  if (
    !scopeMatches(scopeKey) ||
    current?.scopeKey !== activeScopeKey ||
    current?.requestId !== requestId ||
    (attemptId !== undefined && current.attemptId !== attemptId)
  ) {
    return;
  }
  current = {
    ...current,
    promise: null,
    status: "observing",
    observedTurnId,
  };
  emit();
}

export function markChatRequestUncertain(
  requestId: string,
  scopeKey?: string | null,
  attemptId?: number,
) {
  if (
    !scopeMatches(scopeKey) ||
    current?.scopeKey !== activeScopeKey ||
    current?.requestId !== requestId ||
    (attemptId !== undefined && current.attemptId !== attemptId)
  ) {
    return;
  }
  current = {
    ...current,
    promise: null,
    status: "uncertain",
    observedTurnId: undefined,
  };
  emit();
}

export function retryChatRequestAtRevision(
  requestId: string,
  revision: number,
  scopeKey?: string | null,
  attemptId?: number,
) {
  if (
    !scopeMatches(scopeKey) ||
    current?.scopeKey !== activeScopeKey ||
    current?.requestId !== requestId ||
    (attemptId !== undefined && current.attemptId !== attemptId)
  ) {
    return;
  }
  attemptSequence += 1;
  current = {
    ...current,
    attemptId: attemptSequence,
    promise: null,
    revision,
    status: "uncertain",
    observedTurnId: undefined,
  };
  emit();
}

export function adoptPendingChatRequest(
  state: Omit<
    ChatRequestState,
    "attemptId" | "promise" | "scopeKey" | "status" | "observedTurnId"
  >,
  scopeKey?: string | null,
): ChatRequestState | null {
  if (!scopeMatches(scopeKey)) return null;
  if (current?.scopeKey === activeScopeKey && current) return current;
  attemptSequence += 1;
  current = {
    ...state,
    attemptId: attemptSequence,
    scopeKey: activeScopeKey,
    promise: null,
    status: "observing",
    observedTurnId: state.requestId,
  };
  emit();
  return current;
}

export function adoptUncertainChatRequest(
  state: Omit<
    ChatRequestState,
    "attemptId" | "promise" | "scopeKey" | "status" | "observedTurnId"
  >,
  scopeKey?: string | null,
): ChatRequestState | null {
  if (!scopeMatches(scopeKey)) return null;
  if (current?.scopeKey === activeScopeKey && current) return current;
  attemptSequence += 1;
  current = {
    ...state,
    attemptId: attemptSequence,
    scopeKey: activeScopeKey,
    promise: null,
    status: "uncertain",
  };
  emit();
  return current;
}

export function subscribeChatRequest(
  callback: () => void,
  scopeKey?: string | null,
): () => void {
  const listener: Listener = { callback, scopeKey };
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function beginChatRequest(state: NewChatRequestState) {
  const scopeKey = state.scopeKey ?? activeScopeKey;
  if (!scopeMatches(scopeKey)) return;
  const attemptId = state.attemptId ?? createChatRequestAttempt(scopeKey);
  if (attemptId === null || attemptId !== attemptSequence) return;
  const active: ChatRequestState = {
    ...state,
    scopeKey,
    attemptId,
    status: "in_flight",
  };
  current = active;
  settled = null;
  const promise = state.promise;
  if (promise) {
    void promise.then(
      (session) => {
        if (
          activeScopeKey !== active.scopeKey ||
          current?.requestId !== active.requestId ||
          current.attemptId !== active.attemptId
        ) {
          return;
        }
        settled = session;
        current = null;
        emit();
      },
      () => {
        if (
          activeScopeKey !== active.scopeKey ||
          current?.requestId !== active.requestId ||
          current.attemptId !== active.attemptId
        ) {
          return;
        }
        current = {
          ...current,
          promise: null,
          status: current.status === "observing" ? "observing" : "uncertain",
        };
        emit();
      },
    );
  }
  emit();
}

export function abandonChatRequest(
  requestId?: string,
  scopeKey?: string | null,
  attemptId?: number,
) {
  if (!scopeMatches(scopeKey)) return;
  if (requestId && current && current.requestId !== requestId) return;
  if (attemptId !== undefined && current?.attemptId !== attemptId) return;
  current = null;
  emit();
}
