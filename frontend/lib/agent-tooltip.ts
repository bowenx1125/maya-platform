import type { AgentSummary } from "./api/platform";

type Translate = (
  key: "agentLastEditedTooltip",
  values?: Record<string, string>,
) => string;

/** "1.3", "v1.3" or "V1.3" all read "V1.3" (one decimal, as the server labels). */
export function formatVersionLabel(label: string): string {
  const match = /^v?(\d+)\.(\d)$/i.exec(label.trim());
  return match ? `V${match[1]}.${match[2]}` : label.trim();
}

/**
 * Hover text for an Agent button/card: latest version and latest editor.
 * The server names the creator until someone else edits; undefined only when
 * no editor name is known at all.
 */
export function agentLastEditedTitle(
  t: Translate,
  agent: Pick<AgentSummary, "last_edited_by_name" | "current_version_label">,
  fallbackVersion?: string,
): string | undefined {
  const name = agent.last_edited_by_name;
  if (!name) return undefined;
  const version = formatVersionLabel(
    agent.current_version_label ?? fallbackVersion ?? "",
  );
  return t("agentLastEditedTooltip", { name, version: version || "—" });
}
