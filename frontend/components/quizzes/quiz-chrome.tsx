"use client";

import Link from "next/link";
import type { MouseEventHandler, ReactNode } from "react";

import { cn } from "../../lib/utils";
import { BUSY_MOTION, BUSY_MOTION_PRIMARY, PRESS_MOTION } from "../ui/button";
import { WorkspaceIcon, type WorkspaceIconName } from "../workspace-icon";

/**
 * Teacher Quiz pages, owner pick 2026-11-08: option A ("arcade keys",
 * binder cards, clipboard Records, marked paper, sticker empties) with B's
 * blinking LIVE lamp. Every key is a symbol plus a word.
 */

const KEY = `relative inline-flex min-h-11 shrink-0 cursor-pointer items-center gap-1.5 rounded-[10px] border-[3px] border-[#111] px-4 py-[7px] font-body text-sm [line-height:normal] font-extrabold text-[#111] no-underline disabled:cursor-not-allowed disabled:opacity-50 disabled:aria-busy:opacity-100 [&_svg]:size-4 ${PRESS_MOTION}`;

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
    tone === "primary" ? "bg-[#FF4D8D]" : "bg-white",
    tone === "primary" ? BUSY_MOTION_PRIMARY : BUSY_MOTION,
    className,
  );
  const content = (
    <>
      {busy ? (
        <span className="spinner" aria-hidden="true" />
      ) : (
        <WorkspaceIcon name={icon} size={16} stroke={2.6} />
      )}
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

/** B's lamp: blinks while a Quiz accepts submissions; still under reduced motion. */
export function LiveLamp() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border-2 border-[#111] bg-white px-2.5 py-px font-body text-[11px] font-extrabold tracking-[0.06em] text-[#111]">
      <i
        aria-hidden="true"
        className="inline-block size-2.5 rounded-full border-2 border-[#111] bg-[#EF4444] animate-quiz-live motion-reduce:animate-none"
      />
      LIVE
    </span>
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

/** Card offset shadow by state: lime accepting, cyan published, grey draft. */
export const STATE_SHADOW: Record<QuizState, string> = {
  accepting: "shadow-[6px_6px_0_#A3E635]",
  paused: "shadow-[6px_6px_0_#67E8F9]",
  draft: "shadow-[6px_6px_0_#D1D5DB]",
};

const STATE_PILL: Record<QuizState, { bg: string; dot: string }> = {
  accepting: { bg: "bg-[#ECFCCB]", dot: "bg-[#65A30D]" },
  paused: { bg: "bg-[#CFFAFE]", dot: "bg-[#0891B2]" },
  draft: { bg: "bg-[#F3F4F6]", dot: "bg-[#6B7280]" },
};

/** One status pill with a coloured dot in place of separate state chips. */
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
      className={`inline-flex items-center gap-2 rounded-full border-2 border-[#111] px-3 py-1 font-body text-xs font-extrabold text-[#111] ${tone.bg}`}
    >
      <i
        aria-hidden="true"
        className={`inline-block size-2.5 rounded-full ${tone.dot}`}
      />
      {label}
    </span>
  );
}

/** A plain chip beside the status pill (date, attempts). */
export function QuizChip({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full border-2 border-[#111] bg-white px-3 py-1 font-body text-xs font-bold text-[#111]">
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
      className={`group grid min-h-[280px] place-items-center content-center gap-[18px] rounded-2xl border-[3px] border-[#111] bg-white p-7 text-center ${EMPTY_CARD[kind]}`}
    >
      <span
        aria-hidden="true"
        className={`grid size-[88px] place-items-center rounded-[18px] border-[3px] border-[#111] text-[#111] ${EMPTY_TILE[kind]}`}
      >
        <WorkspaceIcon name={EMPTY_ICON[kind]} size={44} stroke={2.2} />
      </span>
      <h2 className="m-0 -rotate-2 rounded-xl border-[3px] border-[#111] bg-[#FFE14D] px-[18px] py-2 font-display text-[22px] leading-tight font-extrabold text-[#111] shadow-[4px_4px_0_#FDE68A] transition-[rotate] duration-[400ms] ease-[cubic-bezier(.2,.8,.2,1)] group-hover:-rotate-6 motion-reduce:transition-none motion-reduce:group-hover:-rotate-2">
        {title}
      </h2>
    </section>
  );
}

/**
 * The Record clipboard (paper, dot grid, purple clip, tilted title, red
 * stamp) that Quiz submissions share with the chat Record board below.
 */
export function ClipboardBoard({
  title,
  stamp,
  children,
}: {
  title: string;
  stamp: string;
  children: ReactNode;
}) {
  return (
    <section
      aria-label={title}
      className="relative mx-auto w-full min-w-0 max-w-[1120px] rounded-[10px] border-4 border-[#111] bg-[#F5E6C8] bg-[radial-gradient(#E9DFC4_1.4px,transparent_1.4px)] bg-[length:22px_22px] px-9 pt-14 pb-10 shadow-[10px_10px_0_#67E8F9] max-[520px]:px-4"
    >
      <span
        aria-hidden="true"
        className="absolute top-[-20px] left-1/2 h-9 w-[120px] -translate-x-1/2 rounded-t-lg rounded-b-sm border-[3px] border-[#111] bg-[#C4B5FD] shadow-[inset_0_-6px_0_#A78BFA]"
      />
      <div className="mb-[22px] flex flex-wrap items-start gap-3.5">
        <h2 className="m-0 max-w-full -rotate-[1.5deg] rounded-md border-[3px] border-l-[10px] border-[#111] border-l-[#FACC15] bg-white px-[18px] py-1 font-display text-[32px] leading-tight font-extrabold break-words text-[#111] shadow-[4px_4px_0_#FFE14D] max-[520px]:text-[26px]">
          {title}
        </h2>
        <span
          aria-hidden="true"
          className="ml-auto rotate-[8deg] rounded-lg border-[3px] border-[#EF4444] bg-white/85 px-3.5 py-1.5 text-[13px] font-extrabold text-[#EF4444]"
        >
          {stamp}
        </span>
      </div>
      {children}
    </section>
  );
}
