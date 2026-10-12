import {
  isAmbiguousMutationFailure,
  type IdempotencyHandle,
} from "../../lib/api";

type KnowledgeMutationStore = {
  handleFor: (intent: string) => IdempotencyHandle;
  finish: (intent: string, expected?: IdempotencyHandle) => void;
  abandon: (intent: string, expected?: IdempotencyHandle) => void;
};

/** Keep one key for an uncertain mutation and release it only on a settled result. */
export async function runKnowledgeMutation<T>(
  store: KnowledgeMutationStore,
  intent: string,
  request: (idempotency: IdempotencyHandle) => Promise<T>,
): Promise<T> {
  const idempotency = store.handleFor(intent);
  try {
    const result = await request(idempotency);
    store.finish(intent, idempotency);
    return result;
  } catch (cause) {
    if (!isAmbiguousMutationFailure(cause)) {
      store.abandon(intent, idempotency);
    }
    throw cause;
  }
}
