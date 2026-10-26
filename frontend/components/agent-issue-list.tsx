"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { cn } from "../lib/utils";
import { NOTICE_TAIL_CLASS, useNoticeTray } from "./ui";

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

/** One problem on a create form: a field to show, or an Agent to edit. */
export type ChecklistItem = {
  key: string;
  text: string;
  /** Id of the field that "Show me" scrolls to and focuses. */
  target?: string;
  /** The Agent this line is about, so its card wears the same number. */
  agentId?: string;
  href?: string;
  editLabel?: string;
};
export type ChecklistEntry = ChecklistItem & { n: number; done: boolean };

/**
 * Numbers the problems of the latest attempt. A line that is fixed stays in
 * place, ticked and struck through, until the next attempt starts a new list.
 */
export function useCreateChecklist(
  items: ChecklistItem[],
  attempt: number,
): ChecklistEntry[] {
  const [snapshot, setSnapshot] = useState({ attempt, items });
  let base = snapshot;
  if (snapshot.attempt !== attempt) {
    base = { attempt, items };
    setSnapshot(base);
  } else {
    const extra = items.filter(
      (item) => !snapshot.items.some((seen) => seen.key === item.key),
    );
    if (extra.length) {
      base = { attempt, items: [...snapshot.items, ...extra] };
      setSnapshot(base);
    }
  }
  return base.items.map((seen, index) => {
    const live = items.find((item) => item.key === seen.key);
    return { ...(live ?? seen), n: index + 1, done: !live };
  });
}

export const checklistLineId = (n: number) => `create-issue-${n}`;

/** The red number on a field or Agent card; green ✓ once its line is fixed. */
export function ChecklistBadge({ entry }: { entry?: ChecklistEntry }) {
  if (!entry) return null;
  return (
    <span
      aria-hidden="true"
      data-checklist-badge
      className={`absolute -top-2.5 -left-2.5 z-[2] size-[22px] rounded-full border-2 border-border text-center font-body text-xs leading-[18px] font-extrabold text-white ${entry.done ? "bg-ok" : "bg-err"}`}
    >
      {entry.done ? "✓" : entry.n}
    </span>
  );
}

const CHECKLIST_BUTTON =
  "flex-none cursor-pointer whitespace-nowrap rounded-[6px] border-2 border-border bg-surface px-2.5 py-[3px] font-body text-xs font-bold text-ink no-underline shadow-[0_3px_0_#111] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main";

/**
 * The create form's problems, spoken once by the mascot (06 option A): the
 * title, then every problem as a numbered line with its own jump.
 */
export function CreateChecklist({
  title,
  entries,
  alert = false,
  attempt,
}: {
  title: string;
  entries: ChecklistEntry[];
  alert?: boolean;
  attempt: number;
}) {
  const t = useT();
  const tray = useNoticeTray(true);
  const [dismissed, setDismissed] = useState<number | null>(null);
  if (!tray || dismissed === attempt) return null;
  if (entries.length === 0 || entries.every((entry) => entry.done)) return null;
  const show = (target: string) => {
    const element = document.getElementById(target);
    element?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    element?.focus({ preventScroll: true });
  };
  return createPortal(
    <div
      className={cn(
        "notice agent-hint-bar agent-hint-bar-bubble relative w-full rounded-[18px] border-[3px] border-border py-3 pr-10 pl-3.5 text-left font-body text-[13px] leading-[1.45] font-medium text-ink shadow-[4px_4px_0_#111]",
        alert ? "notice-error bg-err-bg" : "notice-warning bg-warn-bg",
        "pointer-events-auto flex-none",
        NOTICE_TAIL_CLASS,
      )}
      role={alert ? "alert" : "note"}
      aria-live={alert ? undefined : "polite"}
    >
      <strong>{title}</strong>
      <ol className="m-0 mt-1.5 list-none p-0">
        {entries.map((entry) => (
          <li
            key={entry.key}
            id={checklistLineId(entry.n)}
            data-done={entry.done || undefined}
            className={cn(
              "flex items-start gap-2 border-t-2 border-dashed border-[#1112] py-1.5",
              entry.done && "text-[#6B7280] line-through",
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "size-5 flex-none rounded-full border-2 border-border text-center text-[11px] leading-4 font-extrabold text-white",
                entry.done ? "bg-ok" : "bg-err",
              )}
            >
              {entry.done ? "✓" : entry.n}
            </span>
            <span className="flex-1">{entry.text}</span>
            {entry.done ? null : entry.href ? (
              <Link
                className={CHECKLIST_BUTTON}
                href={entry.href}
                aria-label={entry.editLabel}
              >
                {entry.editLabel}
              </Link>
            ) : entry.target ? (
              <button
                type="button"
                className={CHECKLIST_BUTTON}
                onClick={() => show(entry.target!)}
              >
                {t("debateShowMe")}
              </button>
            ) : null}
          </li>
        ))}
      </ol>
      <button
        type="button"
        className="notice-close absolute top-2 right-2.5 grid size-[22px] cursor-pointer place-items-center rounded-full border-2 border-border bg-surface text-ink focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main"
        aria-label={t("noticeDismiss")}
        onClick={() => setDismissed(attempt)}
      >
        <IconClose />
      </button>
    </div>,
    tray,
  );
}
