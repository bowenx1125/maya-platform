"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
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

/** Keycap (14 option B): black key on a red key-shadow; pressed green ✓ when fixed. */
const KEYCAP =
  "flex-none rounded-[7px] border-2 border-border text-center font-body font-extrabold";
const KEYCAP_TONE = (done: boolean) =>
  done
    ? "grid place-items-center bg-[#22C55E] text-ink shadow-[0_1px_0_#111]"
    : "bg-[#111] text-white";

/** The number on a field or Agent card; pressed green ✓ once its line is fixed. */
export function ChecklistBadge({ entry }: { entry?: ChecklistEntry }) {
  if (!entry) return null;
  return (
    <span
      aria-hidden="true"
      data-checklist-badge
      data-done={entry.done || undefined}
      className={cn(
        KEYCAP,
        "absolute -top-3 -left-3 z-[5] h-7 min-w-7 px-1 text-[13px] leading-6",
        KEYCAP_TONE(entry.done),
        entry.done ? "translate-y-[3px]" : "shadow-[0_4px_0_#EF4444]",
      )}
    >
      {entry.done ? "✓" : entry.n}
    </span>
  );
}

/** The white keycap jump button with its aria-hidden ↵ key. */
export const KEYCAP_BUTTON =
  "mb-[3px] inline-flex flex-none cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-lg border-2 border-border bg-surface px-2.5 py-[5px] font-body text-xs font-bold text-ink no-underline shadow-[0_4px_0_#111] hover:bg-[#FFE14D] active:translate-y-1 active:bg-[#FFE14D] active:shadow-[0_0_0_#111] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main motion-reduce:active:translate-y-0";

export function KeycapGlyph() {
  return (
    <kbd
      aria-hidden="true"
      className="border-l-2 border-border pl-1.5 font-body text-[11px] font-extrabold"
    >
      ↵
    </kbd>
  );
}

/** One checklist line: a key-row card that sinks flat, struck in red, when fixed. */
export function ChecklistLine({
  entry,
  children,
}: {
  entry: ChecklistEntry;
  children?: ReactNode;
}) {
  return (
    <li
      id={checklistLineId(entry.n)}
      data-done={entry.done || undefined}
      className={cn(
        "mb-[7px] flex items-center gap-2.5 rounded-[10px] border-2 px-2 py-[7px] max-[680px]:flex-wrap",
        entry.done
          ? "translate-y-[3px] border-[#9CA3AF] bg-[#F1F5F9]"
          : "border-border bg-surface shadow-[0_3px_0_#111] hover:bg-[#FFF7CC] active:translate-y-[3px] active:shadow-none motion-reduce:active:translate-y-0",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          KEYCAP,
          "size-[26px] text-xs leading-[22px]",
          KEYCAP_TONE(entry.done),
          entry.done ? "translate-y-0.5" : "shadow-[0_3px_0_#EF4444]",
        )}
      >
        {entry.done ? "✓" : entry.n}
      </span>
      <span
        className={cn(
          "flex-1 max-[680px]:basis-[calc(100%-40px)]",
          entry.done &&
            "text-[#6B7280] line-through decoration-[#EF4444] decoration-[3px]",
        )}
      >
        {entry.text}
      </span>
      {entry.done ? null : children}
    </li>
  );
}

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
        "notice agent-hint-bar agent-hint-bar-bubble relative! top-auto! m-0! block! w-full rounded-[18px] border-[3px]! border-border! pt-[13px]! pr-[46px]! pb-3! pl-4! text-left font-body text-[13px] leading-[1.45] font-medium text-ink shadow-[4px_4px_0_#111]! max-[680px]:pt-[11px]! max-[680px]:pr-10! max-[680px]:pb-2.5! max-[680px]:pl-3! max-[680px]:text-xs!",
        alert ? "notice-error bg-err-bg" : "notice-warning bg-warn-bg",
        "pointer-events-auto flex-none",
        NOTICE_TAIL_CLASS,
      )}
      role={alert ? "alert" : "note"}
      aria-live={alert ? undefined : "polite"}
    >
      <strong className="mb-1.5 block text-sm font-bold">{title}</strong>
      <ol className="m-0 list-none p-0">
        {entries.map((entry) => (
          <ChecklistLine key={entry.key} entry={entry}>
            {entry.href ? (
              <Link
                className={cn(KEYCAP_BUTTON, "max-[680px]:ml-[34px]")}
                href={entry.href}
                aria-label={entry.editLabel}
              >
                {entry.editLabel}
                <KeycapGlyph />
              </Link>
            ) : entry.target ? (
              <button
                type="button"
                className={cn(KEYCAP_BUTTON, "max-[680px]:ml-[34px]")}
                onClick={() => show(entry.target!)}
              >
                {t("debateShowMe")}
                <KeycapGlyph />
              </button>
            ) : null}
          </ChecklistLine>
        ))}
      </ol>
      <button
        type="button"
        className="notice-close absolute! top-[9px] right-2.5 m-0! grid size-[26px] cursor-pointer place-items-center rounded-full border-2 border-border bg-surface text-ink focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main"
        aria-label={t("noticeDismiss")}
        onClick={() => setDismissed(attempt)}
      >
        <IconClose />
      </button>
    </div>,
    tray,
  );
}
