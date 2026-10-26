"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { cn } from "../lib/utils";
import {
  NOTICE_TAIL_CLASS,
  STICKER,
  STICKER_TONE,
  StickerBadge,
  useNoticeTray,
} from "./ui";

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

/** The number sticker on a field or Agent card; ✓ once its line is fixed. */
export function ChecklistBadge({ entry }: { entry?: ChecklistEntry }) {
  if (!entry) return null;
  return <StickerBadge n={entry.n} done={entry.done} />;
}

/** The pink pill jump button ("Show me" / "Edit Agent …") with its → arrow. */
export const JUMP_BUTTON =
  "inline-flex flex-none cursor-pointer items-center gap-[5px] whitespace-nowrap rounded-full border-2 border-border bg-[#FF4D8D] px-[11px] py-1 font-body text-xs font-bold text-ink no-underline shadow-[3px_3px_0_#111] hover:-translate-x-px hover:-translate-y-px hover:shadow-[4px_4px_0_#111] active:translate-x-[3px] active:translate-y-[3px] active:shadow-none focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main motion-reduce:hover:translate-0 motion-reduce:active:translate-0";

export function JumpArrow() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 12h13M13 6l6 6-6 6" />
    </svg>
  );
}

/** One checklist line: dashed rule between lines; grey with a black strike once fixed. */
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
        "group/line flex items-center gap-2.5 border-t-2 border-dashed border-[#11111833] py-[7px] first:border-t-0 max-[680px]:flex-wrap",
        !entry.done &&
          "active:-mx-2 active:rounded-lg active:bg-[#FFD0D0] active:px-2",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          STICKER,
          "size-6 text-[11px] leading-5",
          STICKER_TONE(entry.done),
        )}
      >
        {entry.done ? "✓" : entry.n}
      </span>
      <span
        className={cn(
          "flex-1 max-[680px]:basis-[calc(100%-40px)]",
          entry.done
            ? "text-[#6B7280] line-through decoration-ink decoration-2"
            : "decoration-[#FF4D8D] decoration-2 underline-offset-[3px] group-hover/line:underline",
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
                className={cn(JUMP_BUTTON, "max-[680px]:ml-[34px]")}
                href={entry.href}
                aria-label={entry.editLabel}
              >
                {entry.editLabel}
                <JumpArrow />
              </Link>
            ) : entry.target ? (
              <button
                type="button"
                className={cn(JUMP_BUTTON, "max-[680px]:ml-[34px]")}
                onClick={() => show(entry.target!)}
              >
                {t("debateShowMe")}
                <JumpArrow />
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
