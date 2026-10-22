import { PlatformApiError, type KnowledgeDocument } from "./api";

/**
 * A course teacher edits a student's public Agent (PR #229) without joining
 * its group, while the group library stays closed (404) to a teacher who has
 * not joined. The Agent editor then offers only the sources already bound to
 * the version instead of failing the whole load as "Agent not found".
 */
export function groupLibraryOrClosed(
  library: Promise<KnowledgeDocument[]>,
): Promise<KnowledgeDocument[]> {
  return library.catch((cause: unknown) => {
    if (cause instanceof PlatformApiError && cause.status === 404) return [];
    throw cause;
  });
}
