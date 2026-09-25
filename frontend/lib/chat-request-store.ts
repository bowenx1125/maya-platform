import type { ChatSession } from "./api";

/**
 * Holds the in-flight chat send while AgentChat is mounted. Leaving the page
 * or switching conversations aborts that send; this store does not continue it.
 */
export type ChatRequestState = {
  sessionId: string | null;
  versionId: string;
  message: string;
  requestId: string;
  revision: number;
  /** Null after a failed attempt so a retry can reopen the same request_id. */
  promise: Promise<ChatSession> | null;
};

type Listener = () => void;

let current: ChatRequestState | null = null;
let settled: ChatSession | null = null;
const listeners = new Set<Listener>();

function emit() {
  for (const listener of listeners) listener();
}

export function getChatRequest(): ChatRequestState | null {
  return current;
}

export function getSettledChatSession(): ChatSession | null {
  return settled;
}

export function clearSettledChatSession() {
  settled = null;
}

export function subscribeChatRequest(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function beginChatRequest(state: ChatRequestState) {
  current = state;
  settled = null;
  const promise = state.promise;
  if (promise) {
    void promise.then(
      (session) => {
        if (current?.requestId !== state.requestId) return;
        settled = session;
        current = null;
        emit();
      },
      () => {
        if (current?.requestId !== state.requestId) return;
        current = { ...current, promise: null };
        emit();
      },
    );
  }
  emit();
}

export function abandonChatRequest(requestId?: string) {
  if (requestId && current && current.requestId !== requestId) return;
  current = null;
  emit();
}
