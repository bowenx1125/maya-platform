"use client";

import Link from "next/link";
import type { MouseEventHandler, ReactNode } from "react";

import { cn } from "../../lib/utils";
import { BUSY_MOTION, BUSY_MOTION_PRIMARY, PRESS_MOTION } from "../ui/button";
import { IconLock } from "../quiet-icons";
import { WorkspaceIcon, type WorkspaceIconName } from "../workspace-icon";

/**
 * Quiz pages, owner pick 2026-11-08 (second round): option A "one page per
 * quiz". Lists are plain rows with one state chip; a quiz opens on its own
 * page with Paper | Submissions. Every key is a symbol plus a word.
 */

const KEY = `relative inline-flex min-h-11 shrink-0 cursor-pointer items-center gap-1.5 rounded-arc border-[3px] border-border px-4 py-[7px] font-body text-sm [line-height:normal] font-extrabold text-ink no-underline disabled:cursor-not-allowed disabled:opacity-50 disabled:aria-busy:opacity-100 [&_svg]:size-4 ${PRESS_MOTION}`;

/** Under 600px a key shows its symbol above its word (handoff §4). */
const KEY_STACKED =
  "max-[600px]:min-w-0 max-[600px]:flex-col max-[600px]:justify-center max-[600px]:gap-1 max-[600px]:px-2 max-[600px]:py-2 max-[600px]:text-xs";

/** A row of keys; under 600px it becomes an even grid. */
export const KEY_ROW =
  "flex flex-wrap gap-2.5 max-[600px]:grid max-[600px]:w-full max-[600px]:grid-cols-[repeat(auto-fit,minmax(88px,1fr))]";

export function QuizKey({
  icon,
  children,
  tone = "neutral",
  href,
  busy,
  disabled,
  onClick,
  className,
  ariaLabel,
  testId,
  guide,
}: {
  icon: WorkspaceIconName;
  children: ReactNode;
  /** One primary (pink) per row; destructive or undo keys stay neutral. */
  tone?: "primary" | "neutral";
  href?: string;
  busy?: boolean;
  disabled?: boolean;
  onClick?: MouseEventHandler<HTMLButtonElement | HTMLAnchorElement>;
  className?: string;
  ariaLabel?: string;
  testId?: string;
  /** data-ui-guide hook, kept when a key is restyled. */
  guide?: string;
}) {
  const classes = cn(
    KEY,
    KEY_STACKED,
    tone === "primary" ? "bg-main" : "bg-white",
    tone === "primary" ? BUSY_MOTION_PRIMARY : BUSY_MOTION,
    className,
  );
  // Busy keeps the symbol and the word: the shared fill is the only
  // loading a key shows (handoff §2), no spinner in their place.
  const content = (
    <>
      <WorkspaceIcon name={icon} size={16} stroke={2.6} />
      <span>{children}</span>
    </>
  );
  if (href) {
    return (
      <Link
        href={href}
        className={classes}
        aria-label={ariaLabel}
        data-testid={testId}
        data-ui-guide={guide}
        onClick={onClick}
      >
        {content}
      </Link>
    );
  }
  return (
    <button
      type="button"
      className={classes}
      aria-label={ariaLabel}
      aria-busy={busy || undefined}
      data-testid={testId}
      data-ui-guide={guide}
      disabled={Boolean(disabled || busy) || undefined}
      onClick={onClick}
    >
      {content}
    </button>
  );
}

export type QuizState = "draft" | "paused" | "accepting";

export function quizState(quiz: {
  status: string;
  taking_open?: boolean | null;
}): QuizState {
  if (quiz.status !== "published") return "draft";
  return quiz.taking_open === true ? "accepting" : "paused";
}

const STATE_PILL: Record<QuizState, { bg: string; dot: string }> = {
  accepting: { bg: "bg-[#ECFCCB]", dot: "bg-[#65A30D]" },
  paused: { bg: "bg-[#CFFAFE]", dot: "bg-[#0891B2]" },
  draft: { bg: "bg-[#F3F4F6]", dot: "bg-[#6B7280]" },
};

/**
 * The one state chip a quiz shows: a blinking LIVE lamp while it accepts
 * submissions (B's lamp), otherwise Paused or Draft with a dot.
 */
export function QuizStatus({
  state,
  label,
}: {
  state: QuizState;
  label: string;
}) {
  const tone = STATE_PILL[state];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-2 rounded-full border-2 border-border px-3 py-1 font-body text-xs font-extrabold text-ink ${tone.bg}`}
      data-testid="quiz-state"
    >
      {state === "accepting" ? (
        <>
          <i
            aria-hidden="true"
            className="inline-block size-2.5 rounded-full border-2 border-border bg-[#EF4444] animate-quiz-live motion-reduce:animate-none"
          />
          <span aria-hidden="true" className="tracking-[0.06em]">
            LIVE
          </span>
          <span className="sr-only">{label}</span>
        </>
      ) : (
        <>
          <i
            aria-hidden="true"
            className={`inline-block size-2.5 rounded-full ${tone.dot}`}
          />
          {label}
        </>
      )}
    </span>
  );
}

/** A plain chip beside the status pill (date, attempts). */
export function QuizChip({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full border-2 border-border bg-white px-3 py-1 font-body text-xs font-bold text-ink">
      {children}
    </span>
  );
}

const EMPTY_TILE: Record<"quiz" | "records" | "course", string> = {
  quiz: "bg-[#67E8F9] shadow-[4px_4px_0_#A5F3FC]",
  records: "bg-[#FBCFE8] shadow-[4px_4px_0_#FCE7F3]",
  course: "bg-[#C4B5FD] shadow-[4px_4px_0_#DDD6FE]",
};

const EMPTY_CARD: Record<"quiz" | "records" | "course", string> = {
  quiz: "shadow-[6px_6px_0_#67E8F9]",
  records: "shadow-[6px_6px_0_#FF4D8D]",
  course: "shadow-[6px_6px_0_#C4B5FD]",
};

const EMPTY_ICON: Record<"quiz" | "records" | "course", WorkspaceIconName> = {
  quiz: "quiz",
  records: "clock",
  course: "classroom",
};

/**
 * A's sticker empty card: an icon tile and the existing one-line copy on a
 * tilted yellow sticker. Shown only when the request succeeded with no rows.
 */
export function QuizEmpty({
  title,
  kind,
}: {
  title: string;
  kind: "quiz" | "records" | "course";
}) {
  return (
    <section
      className={`group grid min-h-[280px] place-items-center content-center gap-[18px] rounded-2xl border-[3px] border-border bg-white p-7 text-center ${EMPTY_CARD[kind]}`}
    >
      <span
        aria-hidden="true"
        className={`grid size-[88px] place-items-center rounded-[18px] border-[3px] border-border text-ink ${EMPTY_TILE[kind]}`}
      >
        <WorkspaceIcon name={EMPTY_ICON[kind]} size={44} stroke={2.2} />
      </span>
      <h2 className="m-0 -rotate-2 rounded-xl border-[3px] border-border bg-[#FFE14D] px-[18px] py-2 font-display text-[22px] leading-tight font-extrabold text-ink shadow-[4px_4px_0_#FDE68A] transition-[rotate] duration-[400ms] ease-[cubic-bezier(.2,.8,.2,1)] group-hover:-rotate-6 motion-reduce:transition-none motion-reduce:group-hover:-rotate-2">
        {title}
      </h2>
    </section>
  );
}

/** A's list row card. The row opens its page; Delete quiz sits beside the link. */
export const QUIZ_ROW_SHELL =
  "relative flex flex-wrap items-center gap-x-3.5 gap-y-2.5 rounded-[14px] border-[3px] border-border bg-white shadow-[4px_4px_0_#111]";
export const QUIZ_ROW = `${QUIZ_ROW_SHELL} px-[18px] py-4`;

export type QuizTabSpec<T extends string> = {
  value: T;
  label: string;
  count?: number;
  /** Shown as a locked tab with this reason as its tooltip. */
  lockedReason?: string;
};

/** Paper | Submissions: the one switch between editing and the record. */
export function QuizTabs<T extends string>({
  label,
  tabs,
  value,
  onChange,
}: {
  label: string;
  tabs: QuizTabSpec<T>[];
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className="inline-flex max-w-full self-start overflow-hidden rounded-[12px] border-[3px] border-border shadow-[4px_4px_0_#111]"
    >
      {tabs.map((tab) => {
        const selected = tab.value === value;
        const locked = Boolean(tab.lockedReason);
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-disabled={locked || undefined}
            title={tab.lockedReason}
            onClick={() => {
              if (!locked) onChange(tab.value);
            }}
            className={cn(
              "inline-flex min-h-11 items-center gap-2 border-0 border-r-[3px] border-border px-[18px] font-body text-sm font-extrabold last:border-r-0",
              selected
                ? "bg-main text-ink"
                : locked
                  ? "cursor-not-allowed bg-[#F3F4F6] text-arc-muted"
                  : "cursor-pointer bg-white text-ink hover:bg-warn-bg",
            )}
          >
            {locked ? <IconLock size={14} /> : null}
            {tab.label}
            {tab.count !== undefined && !locked ? (
              <span className="rounded-full border-2 border-border bg-white px-2 font-mono text-xs">
                {tab.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
