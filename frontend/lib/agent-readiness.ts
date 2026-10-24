import type { MessageKey } from "./i18n";

export type AgentIssueKind =
  | "agent_archived"
  | "agent_not_published"
  | "rag_missing"
  | "agent_md_invalid"
  | "avatar_missing"
  | "voice_missing";

export type AgentIssue = {
  agent_id: string;
  agent_name: string;
  issue: AgentIssueKind;
};

export const AGENT_ISSUE_MESSAGES: Record<AgentIssueKind, MessageKey> = {
  agent_archived: "agentIssueArchived",
  agent_not_published: "agentIssueNotPublished",
  rag_missing: "agentIssueRagMissing",
  agent_md_invalid: "agentIssueAgentMdInvalid",
  avatar_missing: "agentIssueAvatarMissing",
  voice_missing: "agentIssueVoiceMissing",
};

const HEADING = /^#{1,6}\s+\S/m;

/** The one AGENT.md rule the server states: a # heading and some text. */
export function agentMdIsStandard(markdown: string): boolean {
  if (!HEADING.test(markdown)) return false;
  return markdown
    .split(/\r?\n/)
    .some((line) => line.trim() !== "" && !line.trimStart().startsWith("#"));
}

/** The per-Agent issues a refused Debate create carries, if that is what this is. */
export function agentIssuesFromError(error: unknown): AgentIssue[] | null {
  if (!error || typeof error !== "object") return null;
  const { code, details } = error as { code?: unknown; details?: unknown };
  if (code !== "debate_agents_not_ready" || !details) return null;
  const issues = (details as { issues?: unknown }).issues;
  if (!Array.isArray(issues)) return null;
  const parsed = issues.filter(
    (item): item is AgentIssue =>
      Boolean(item) &&
      typeof item === "object" &&
      typeof (item as AgentIssue).agent_id === "string" &&
      typeof (item as AgentIssue).agent_name === "string" &&
      typeof (item as AgentIssue).issue === "string" &&
      (item as AgentIssue).issue in AGENT_ISSUE_MESSAGES,
  );
  return parsed.length ? parsed : null;
}

/** What the Agent page and the Debate form can tell from the version alone. */
export function versionIssues(
  agent: { id: string; name: string },
  version: {
    agent_md?: string | null;
    voice_profile_id?: string | null;
    knowledge_snapshot_id?: string | null;
  },
  { ragCount }: { ragCount?: number } = {},
): AgentIssue[] {
  const found: AgentIssueKind[] = [];
  const hasRag =
    ragCount === undefined
      ? Boolean(version.knowledge_snapshot_id)
      : ragCount > 0;
  if (!hasRag) found.push("rag_missing");
  if (!version.voice_profile_id) found.push("voice_missing");
  if (!agentMdIsStandard(version.agent_md ?? ""))
    found.push("agent_md_invalid");
  return found.map((issue) => ({
    agent_id: agent.id,
    agent_name: agent.name,
    issue,
  }));
}
