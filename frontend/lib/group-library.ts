import { PlatformApiError, type KnowledgeDocument } from "./api";

/**
 * The group library is a membership resource. A course teacher who has entered
 * the group is a temporary member and receives the same library as a groupmate.
 * A teacher who has not entered still gets 404; the editor then keeps the
 * version's bound sources instead of failing the whole load.
 */
export function groupLibraryOrClosed(
  library: Promise<KnowledgeDocument[]>,
): Promise<KnowledgeDocument[]> {
  return library.catch((cause: unknown) => {
    if (cause instanceof PlatformApiError && cause.status === 404) return [];
    throw cause;
  });
}
