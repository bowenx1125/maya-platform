import { PlatformApiError, type KnowledgeDocument } from "./api";

/**
 * Soft-fail a library list that answers 404 so AgentWorkbench can still open.
 *
 * Group library: a course teacher who has entered the group is a temporary
 * member and receives the same library as a groupmate. A teacher who has not
 * entered still gets 404.
 *
 * Personal workspace (`GET /courses/{id}/workspace-documents`): teacher-owned
 * only. Course students (and anyone else) who may edit a teacher Public Agent
 * get 404 here; the editor keeps the version's bound sources instead of
 * failing the whole load.
 */
export function groupLibraryOrClosed(
  library: Promise<KnowledgeDocument[]>,
): Promise<KnowledgeDocument[]> {
  return library.catch((cause: unknown) => {
    if (cause instanceof PlatformApiError && cause.status === 404) return [];
    throw cause;
  });
}
