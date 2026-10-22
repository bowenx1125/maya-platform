import type { AgentVersion } from "./api";

/**
 * The losing editor's unpublished Agent edits, kept in this browser only.
 *
 * Owner decision (2026-10-22): when a concurrent Done loses (409), the edits
 * are stored in localStorage keyed per Agent + user, restored straight into
 * the editor on top of the latest version after refresh, and cleared once a
 * Done succeeds. Nothing is stored on the server.
 */
export type AgentDraftStash = {
  agent_md: string;
  avatar_config: AgentVersion["avatar_config"] | null;
  voice_profile_id: string | null;
  document_ids: string[];
  base_version_id: string | null;
  saved_at: string;
};

const PREFIX = "maya.agent-draft.v1";

export function agentDraftStashKey(userId: string, agentId: string): string {
  return `${PREFIX}:${userId}:${agentId}`;
}

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function saveAgentDraftStash(
  userId: string | undefined,
  agentId: string | undefined,
  draft: Omit<AgentDraftStash, "saved_at">,
): void {
  if (!userId || !agentId) return;
  try {
    storage()?.setItem(
      agentDraftStashKey(userId, agentId),
      JSON.stringify({ ...draft, saved_at: new Date().toISOString() }),
    );
  } catch {
    // Quota or privacy mode: the in-page editor still holds the edits.
  }
}

export function loadAgentDraftStash(
  userId: string | undefined,
  agentId: string | undefined,
): AgentDraftStash | null {
  if (!userId || !agentId) return null;
  try {
    const raw = storage()?.getItem(agentDraftStashKey(userId, agentId));
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<AgentDraftStash>;
    if (typeof value.agent_md !== "string") return null;
    return {
      agent_md: value.agent_md,
      avatar_config: value.avatar_config ?? null,
      voice_profile_id: value.voice_profile_id ?? null,
      document_ids: Array.isArray(value.document_ids)
        ? value.document_ids.filter(
            (id): id is string => typeof id === "string",
          )
        : [],
      base_version_id: value.base_version_id ?? null,
      saved_at: value.saved_at ?? "",
    };
  } catch {
    return null;
  }
}

export function clearAgentDraftStash(
  userId: string | undefined,
  agentId: string | undefined,
): void {
  if (!userId || !agentId) return;
  try {
    storage()?.removeItem(agentDraftStashKey(userId, agentId));
  } catch {
    // Nothing to clear.
  }
}
