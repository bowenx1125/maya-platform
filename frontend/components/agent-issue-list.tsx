"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import {
  AGENT_ISSUE_MESSAGES,
  issueKey,
  type AgentIssue,
} from "../lib/agent-readiness";
import { useT } from "../lib/i18n";
import { IconClose, IconEdit } from "./quiet-icons";
import { WorkspaceIcon } from "./workspace-icon";

/**
 * One line per Agent problem, with a pencil that opens that Agent's editor.
 * Owner decision (2026-10-24): every error names the Agent and its fix.
 */
export function AgentIssueList({
  issues,
  editHref,
  onCheck,
  checking,
}: {
  issues: AgentIssue[];
  editHref?: (agentId: string) => string;
  /** The Agent page's per-line Done: save, publish, then check this line again. */
  onCheck?: (issue: AgentIssue) => void;
  checking?: string | null;
}) {
  const t = useT();
  return (
    <ul className="agent-issue-list">
      {issues.map((item) => {
        const key = issueKey(item);
        const busy = checking === key;
        return (
          <li key={key} data-issue={item.issue}>
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
            {onCheck ? (
              <button
                type="button"
                className="inline-button"
                disabled={Boolean(checking)}
                aria-label={t("agentIssueCheck")}
                title={t("agentIssueCheck")}
                onClick={() => onCheck(item)}
              >
                {busy ? (
                  <span className="spinner" aria-hidden="true" />
                ) : (
                  <WorkspaceIcon name="done" />
                )}
              </button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export type BarLine = { text: string; href: string | null };

/**
 * The one bar every Agent hint and Debate form problem uses: the same look
 * whatever it says, pinned to the top of the page and brought into view when
 * its content changes, so a problem is never below the fold.
 */
export function AgentHintBar({
  title,
  issues = [],
  lines = [],
  editHref,
  onCheck,
  checking,
  onDismiss,
  revealKey,
  alert = false,
}: {
  title: string;
  /** Something must change before the page can go on: announced at once. */
  alert?: boolean;
  issues?: AgentIssue[];
  /** Problems that belong to no Agent (a form field), in the same style;
   * one with an href gets a pencil to the part of the page to edit. */
  lines?: Array<string | BarLine>;
  editHref?: (agentId: string) => string;
  onCheck?: (issue: AgentIssue) => void;
  checking?: string | null;
  onDismiss?: () => void;
  /** Changes when a new problem arrives; the page scrolls back to the bar. */
  revealKey?: string | number;
}) {
  const t = useT();
  const bar = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (revealKey === undefined) return;
    const element = bar.current;
    if (!element || typeof window === "undefined") return;
    if (element.getBoundingClientRect().top < 0) {
      window.scrollTo?.({ top: 0, behavior: "smooth" });
    }
  }, [revealKey]);
  if (issues.length === 0 && lines.length === 0) return null;
  return (
    // A hint is a note screen readers hear without interruption; a problem
    // that stops the page is an alert. The look is the same either way.
    <div
      ref={bar}
      className="agent-hint-bar"
      role={alert ? "alert" : "note"}
      aria-live={alert ? undefined : "polite"}
    >
      <strong>{title}</strong>
      {lines.length ? (
        <ul className="agent-issue-list">
          {lines.map((line) => {
            const { text, href } =
              typeof line === "string" ? { text: line, href: null } : line;
            return (
              <li key={text}>
                <span>{text}</span>
                {href ? (
                  <a
                    className="inline-button"
                    href={href}
                    aria-label={t("debateFieldEdit")}
                    title={t("debateFieldEdit")}
                  >
                    <IconEdit />
                  </a>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      {issues.length ? (
        <AgentIssueList
          issues={issues}
          editHref={editHref}
          onCheck={onCheck}
          checking={checking}
        />
      ) : null}
      {onDismiss ? (
        <button
          type="button"
          className="notice-close"
          aria-label={t("noticeDismiss")}
          onClick={onDismiss}
        >
          <IconClose />
        </button>
      ) : null}
    </div>
  );
}
