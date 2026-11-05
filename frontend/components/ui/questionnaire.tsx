"use client";

// Adapted from neobrutalism.dev questionnaire (MIT), see ./LICENSE.md.
// Adapted to Maya: no @shadcn/react / lucide-react dependency — the checked
// state is owned by props and the check mark is an inline SVG. neobrutalism
// theme tokens that don't exist here map onto the Arcade tokens
// (secondary-background → surface, font-base → font-body, main-foreground →
// main-fg); the thick-border + hard-shadow look comes from PRESS_MOTION
// (ui/button.tsx), like every other pressable in the codebase.
import { cn } from "../../lib/utils";
import { PRESS_MOTION } from "./button";
import type { ReactNode } from "react";

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={3}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      focusable="false"
    >
      <path d="m5 12 4 4L19 6" />
    </svg>
  );
}

export type QuestionnaireChoiceState = {
  type: "radio" | "checkbox";
  checked: boolean;
  disabled?: boolean;
  onSelect: () => void;
};

/** One selectable option. The whole row is the hit target. */
export function QuestionnaireChoice({
  children,
  className,
  state,
}: {
  children: ReactNode;
  className?: string;
  state: QuestionnaireChoiceState;
}) {
  return (
    <button
      type="button"
      role={state.type === "radio" ? "radio" : "checkbox"}
      aria-checked={state.checked}
      disabled={state.disabled}
      data-slot="questionnaire-choice"
      data-type={state.type}
      data-checked={state.checked || undefined}
      onClick={state.onSelect}
      className={cn(
        "group/qc relative flex min-h-11 cursor-pointer items-start gap-3 rounded-arc-s border-[3px] border-border bg-surface px-4 py-3 text-start text-sm font-body font-semibold text-ink select-none",
        PRESS_MOTION,
        "data-checked:bg-main data-checked:text-main-fg",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2",
        "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
    >
      <span
        aria-hidden="true"
        data-slot="questionnaire-choice-indicator"
        className="pointer-events-none relative mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-[4px] border-2 border-border bg-surface text-main-fg group-data-[type=radio]/qc:rounded-full group-data-checked/qc:bg-transparent"
      >
        <CheckIcon className="hidden size-3 group-data-[type=checkbox]/qc:hidden group-data-checked/qc:block" />
        <span className="hidden size-2 rounded-full bg-current group-data-[type=checkbox]/qc:hidden group-data-checked/qc:block" />
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5 leading-snug">
        {children}
      </span>
    </button>
  );
}

/** A grid of options for one item. */
export function QuestionnaireChoices({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      data-slot="questionnaire-choices"
      className={cn("grid min-w-0 gap-3", className)}
    >
      {children}
    </div>
  );
}

/** Short-text / long-text input for one item. */
export function QuestionnaireInput({
  className,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      data-slot="questionnaire-input"
      className={cn(
        "flex min-h-10 w-full min-w-0 rounded-arc-s border-[3px] border-border bg-surface px-3 py-2 text-base font-body font-semibold text-ink",
        "placeholder:text-ink/50",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2",
        "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
        "md:text-sm",
        className,
      )}
      {...props}
    />
  );
}

/** One question block: prompt on top, choices or input below. */
export function QuestionnaireItem({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      data-slot="questionnaire-item"
      className={cn("flex min-w-0 flex-col gap-3 border-0 p-0", className)}
    >
      {children}
    </div>
  );
}

/** The whole form. */
export function Questionnaire({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      data-slot="questionnaire"
      className={cn("flex w-full min-w-0 flex-col gap-6", className)}
    >
      {children}
    </div>
  );
}

/** "Question 2 / 8" progress line. */
export function QuestionnaireProgress({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <p
      data-slot="questionnaire-progress"
      className={cn(
        "m-0 min-h-[1lh] w-fit min-w-[14ch] text-xs font-body font-semibold text-ink tabular-nums",
        className,
      )}
    >
      {children}
    </p>
  );
}

/** Back / Submit row. */
export function QuestionnaireActions({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      data-slot="questionnaire-actions"
      className={cn(
        "flex min-h-11 w-full items-center justify-between gap-2",
        className,
      )}
    >
      {children}
    </div>
  );
}
