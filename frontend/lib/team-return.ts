/**
 * Create Agent opened from an empty Create/Edit Team ("Agents" button) comes
 * back with ?return=. Only a same-origin Teams page path is honoured, so the
 * parameter can never send the user anywhere else.
 */
export function safeTeamsReturn(value: string | null | undefined) {
  if (!value) return undefined;
  if (!/^\/(?:student|teacher)\/teams(?:\?[^#\\]*)?$/.test(value))
    return undefined;
  if (value.includes("//")) return undefined;
  return value;
}

export type TeamDraft = {
  name: string;
  visibility: "private" | "public";
  memberVersionIds: string[];
  leaderVersionId: string;
  sharedSetIds: string[];
};

/** sessionStorage key of a Team form left for Create Agent. */
export function teamDraftKey(scope: string, teamId?: string | null) {
  return `teamDraft:${scope}:${teamId || "new"}`;
}

export function readTeamDraft(key: string): TeamDraft | null {
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<TeamDraft>;
    if (typeof value.name !== "string") return null;
    return {
      name: value.name,
      visibility: value.visibility === "public" ? "public" : "private",
      memberVersionIds: Array.isArray(value.memberVersionIds)
        ? value.memberVersionIds.filter((id) => typeof id === "string")
        : [],
      leaderVersionId:
        typeof value.leaderVersionId === "string" ? value.leaderVersionId : "",
      sharedSetIds: Array.isArray(value.sharedSetIds)
        ? value.sharedSetIds.filter((id) => typeof id === "string")
        : [],
    };
  } catch {
    return null;
  }
}

export function writeTeamDraft(key: string, draft: TeamDraft) {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(draft));
  } catch {
    // Storage full or blocked: the form simply starts empty on return.
  }
}

export function clearTeamDraft(key: string) {
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    // Nothing stored.
  }
}
