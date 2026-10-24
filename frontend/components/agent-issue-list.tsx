"use client";

import Link from "next/link";

import { AGENT_ISSUE_MESSAGES, type AgentIssue } from "../lib/agent-readiness";
import { useT } from "./locale/locale-provider";
import { IconEdit } from "./quiet-icons";

/**
 * One line per Agent problem, with a pencil that opens that Agent's editor.
 * Owner decision (2026-10-24): every error names the Agent and its fix.
 */
export function AgentIssueList({
  issues,
  editHref,
}: {
  issues: AgentIssue[];
  editHref?: (agentId: string) => string;
}) {
  const t = useT();
  return (
    <ul className="agent-issue-list">
      {issues.map((item) => (
        <li key={`${item.agent_id}:${item.issue}`}>
          <span>
            {t(AGENT_ISSUE_MESSAGES[item.issue], { name: item.agent_name })}
          </span>
          {editHref ? (
            <Link
              className="inline-button"
              href={editHref(item.agent_id)}
              aria-label={t("agentIssueEdit", { name: item.agent_name })}
              title={t("agentIssueEdit", { name: item.agent_name })}
            >
              <IconEdit />
            </Link>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
