import type { AffectedAgent } from "./api/platform";

/**
 * Confirm text for deleting a RAG file or Voice. When Agents use it, the
 * list is appended (「会影响这些 Agent：…」) so the user sees who changes.
 * A failed lookup never blocks the delete: the plain confirm still shows.
 */
export async function deleteConfirmText(
  base: string,
  lookup: () => Promise<AffectedAgent[]>,
  affects: (names: string) => string,
): Promise<string> {
  let agents: AffectedAgent[] = [];
  try {
    agents = await lookup();
  } catch {
    agents = [];
  }
  if (agents.length === 0) return base;
  const names = agents.map((agent) => agent.name).join("、");
  return `${base}\n\n${affects(names)}`;
}
