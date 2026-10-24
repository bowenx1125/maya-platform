import type { MessageKey } from "./i18n";

export type AgentIssueKind =
  | "agent_archived"
  | "agent_not_published"
  | "agent_not_current"
  | "agent_not_found"
  | "rag_missing"
  | "agent_md_invalid"
  | "avatar_missing"
  | "voice_missing";

export type AgentIssue = {
  agent_id: string;
  agent_name: string;
  issue: AgentIssueKind;
  /** Only a blocking issue keeps the Agent out of a new Debate. */
  blocking?: boolean;
};

export const AGENT_ISSUE_MESSAGES: Record<AgentIssueKind, MessageKey> = {
  agent_archived: "agentIssueArchived",
  agent_not_published: "agentIssueNotPublished",
  agent_not_current: "agentIssueNotCurrent",
  agent_not_found: "agentIssueNotFound",
  rag_missing: "agentIssueRagMissing",
  agent_md_invalid: "agentIssueAgentMdInvalid",
  avatar_missing: "agentIssueAvatarMissing",
  voice_missing: "agentIssueVoiceMissing",
};

function parseIssues(value: unknown): AgentIssue[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(
      (item): item is AgentIssue =>
        Boolean(item) &&
        typeof item === "object" &&
        typeof (item as AgentIssue).agent_id === "string" &&
        typeof (item as AgentIssue).agent_name === "string" &&
        typeof (item as AgentIssue).issue === "string" &&
        (item as AgentIssue).issue in AGENT_ISSUE_MESSAGES,
    )
    .map((item) => ({
      agent_id: item.agent_id,
      agent_name: item.agent_name,
      issue: item.issue,
      blocking: item.blocking ?? item.issue !== "voice_missing",
    }));
}

/** The per-Agent issues a refused Debate create carries, if that is what this is. */
export function agentIssuesFromError(error: unknown): AgentIssue[] | null {
  if (!error || typeof error !== "object") return null;
  const { code, details } = error as { code?: unknown; details?: unknown };
  if (code !== "debate_agents_not_ready" || !details) return null;
  const parsed = parseIssues((details as { issues?: unknown }).issues);
  return parsed.length ? parsed : null;
}

/** The server's readiness for an Agent's current published version. */
export function readinessIssues(source: {
  readiness_issues?: unknown;
}): AgentIssue[] {
  return parseIssues(source.readiness_issues);
}

export function issueKey(item: AgentIssue): string {
  return `${item.agent_id}:${item.issue}`;
}

/**
 * One list, each Agent problem once. A name the server could not give (an
 * Agent this course no longer sees) is filled from what the page showed.
 */
export function mergeIssues(
  lists: AgentIssue[][],
  names: Record<string, string> = {},
): AgentIssue[] {
  const seen = new Map<string, AgentIssue>();
  for (const list of lists) {
    for (const item of list) {
      const named = item.agent_name
        ? item
        : { ...item, agent_name: names[item.agent_id] ?? "" };
      if (!seen.has(issueKey(named))) seen.set(issueKey(named), named);
    }
  }
  return [...seen.values()];
}

export type FieldProblem = {
  key: MessageKey;
  params?: Record<string, string>;
  /** The form section to edit, when the problem lives in one. */
  anchor?: string;
};

const TOPIC_TYPES = new Set([
  "missing",
  "string_type",
  "string_too_short",
  "topic_blank",
]);

/**
 * A malformed Debate request as sentences, one per field the server named.
 * ``agentNameAt`` turns a participant position into the Agent's name.
 */
export function debateFieldProblems(
  error: unknown,
  agentNameAt: (index: number) => string,
): FieldProblem[] | null {
  if (!error || typeof error !== "object") return null;
  const { code, details } = error as { code?: unknown; details?: unknown };
  if (code !== "malformed_request" || !details) return null;
  const errors = (details as { errors?: unknown }).errors;
  if (!Array.isArray(errors) || errors.length === 0) return null;
  const problems: FieldProblem[] = [];
  const seen = new Set<string>();
  for (const entry of errors) {
    if (!entry || typeof entry !== "object") continue;
    const field = String((entry as { field?: unknown }).field ?? "");
    const type = String((entry as { type?: unknown }).type ?? "");
    const [root, index] = field.split(".");
    const name = index !== undefined ? agentNameAt(Number(index)) : "";
    let problem: FieldProblem;
    if (root === "topic" && TOPIC_TYPES.has(type)) {
      problem = { key: "debateFieldTopicBlank" };
    } else if (root === "participants" && index === undefined) {
      problem = {
        key:
          type === "participants_duplicate"
            ? "debateFieldDuplicateAgent"
            : type === "too_long"
              ? "debateFieldTooManyAgents"
              : "debateFieldTooFewAgents",
      };
    } else if (root === "participants" && type === "assigned_stance_missing") {
      problem = { key: "debateFieldStanceMissing", params: { name } };
    } else if (
      root === "participants" &&
      type === "assigned_stance_unexpected"
    ) {
      problem = { key: "debateFieldStanceUnexpected", params: { name } };
    } else if (root === "participants") {
      problem = { key: "debateFieldAgent", params: { name } };
    } else if (root === "background") {
      problem = { key: "debateFieldBackground" };
    } else if (root === "teaching_prompts") {
      problem = { key: "debateFieldTeachingPrompts" };
    } else if (root === "output_language") {
      problem = { key: "debateFieldOutputLanguage" };
    } else if (root === "llm_params") {
      problem = {
        key: "debateFieldLlmParam",
        params: { field: index ?? "llm_params" },
        anchor: "debate-llm-params",
      };
    } else {
      problem = { key: "debateFieldOther", params: { field: field || "?" } };
    }
    const signature = `${problem.key}:${JSON.stringify(problem.params ?? {})}`;
    if (!seen.has(signature)) {
      seen.add(signature);
      problems.push(problem);
    }
  }
  return problems.length ? problems : null;
}
