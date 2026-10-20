import type { AgentSummary } from "./api/platform";

type Translate = (
  key: "agentLastEditedTooltip",
  values?: Record<string, string>,
) => string;

/** Hover text for an Agent's open link; undefined until someone has edited it. */
export function agentLastEditedTitle(
  t: Translate,
  agent: Pick<AgentSummary, "last_edited_by_name" | "current_version_label">,
  fallbackVersion?: string,
): string | undefined {
  const name = agent.last_edited_by_name;
  if (!name) return undefined;
  const version = (
    agent.current_version_label ??
    fallbackVersion ??
    ""
  ).replace(/^V/i, "");
  return t("agentLastEditedTooltip", { name, version: version || "—" });
}
