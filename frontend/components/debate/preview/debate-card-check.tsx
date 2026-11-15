"use client";

import type { components } from "../../../lib/api/generated/schema";
import type { DebateCardTeacherReason } from "../../../lib/api";
import { useT, type MessageKey } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { IconEye } from "../../quiet-icons";
import { DEBATE_BUTTON, DEBATE_TAG, DEBATE_TAG_TONE } from "../debate-chrome";

export type DebateCard = components["schemas"]["DebateCard"];
export type DebateCardStatus = "compiling" | "ready" | "fallback";

const STATUS: Partial<
  Record<DebateCardStatus, { label: string; tone: keyof typeof DEBATE_TAG_TONE }>
> = {
  compiling: { label: "Compiling", tone: "thinking" },
  ready: { label: "Ready", tone: "ready" },
  // Extraction failure keeps the disclosure and reason body, but no status
  // tag: "Fallback" implied a raw-AGENT.md path that no longer exists.
};

const TEACHER_REASON_COPY: Record<DebateCardTeacherReason, MessageKey> = {
  compile_timeout: "debateCardReasonCompileTimeout",
  format_invalid: "debateCardReasonFormatInvalid",
  card_too_long: "debateCardReasonTooLong",
  service_busy: "debateCardReasonServiceBusy",
  config_problem: "debateCardReasonConfigProblem",
  other: "debateCardReasonOther",
};

const DROP_REASONS: Record<DebateCard["dropped"][number]["reason"], string> = {
  length_limit: "Length limit",
  language_choice: "Language choice",
  output_format: "Output format",
  debate_procedure: "Debate procedure",
  duplicate_translation: "Duplicate translation",
};

/**
 * One Agent's debate card, folded under its name like Check RAG under a turn.
 * Debates created before cards have no status and show nothing.
 */
export function DebateCardCheck({
  agentName,
  status,
  card,
  card_teacher_reason,
}: {
  agentName: string;
  status?: DebateCardStatus | null;
  card?: DebateCard | null;
  card_teacher_reason?: DebateCardTeacherReason | null;
}) {
  const t = useT();
  if (!status) return null;
  const tag = STATUS[status];
  const reasonCopy =
    typeof card_teacher_reason === "string" &&
    Object.hasOwn(TEACHER_REASON_COPY, card_teacher_reason)
      ? TEACHER_REASON_COPY[card_teacher_reason]
      : undefined;
  return (
    <details
      className="font-body [&_summary]:min-h-0 [&_summary]:p-0"
      data-testid="debate-card-check"
    >
      <summary
        className={cn(
          DEBATE_BUTTON,
          "list-none py-1 pr-2.5 pl-2 text-xs leading-[normal] [&::-webkit-details-marker]:hidden",
        )}
        aria-label={`Check ${agentName} card`}
      >
        <IconEye size={18} />
        <span>Check card</span>
        {tag ? (
          <span
            className={cn(
              DEBATE_TAG,
              DEBATE_TAG_TONE[tag.tone],
              "px-[7px] py-0",
            )}
            data-testid="debate-card-status"
          >
            {tag.label}
          </span>
        ) : null}
      </summary>
      <div className="mt-2 grid min-w-0 gap-2 rounded-[12px] border-2 border-[#111] bg-[#F1F7FF] p-2.5 text-sm leading-[1.45] [&_*]:[overflow-wrap:anywhere]">
        {status === "compiling" ? (
          <p className="m-0 text-[#6B7280] italic">
            The card is still compiling. It is settled before this Agent&apos;s
            first speech.
          </p>
        ) : null}
        {status === "fallback" || (status === "ready" && !card) ? (
          <p className="m-0 text-[#6B7280]">
            {t(reasonCopy ?? "debateCardReasonOther")}
          </p>
        ) : null}
        {status === "ready" && card ? <CardBody card={card} /> : null}
      </div>
    </details>
  );
}

function CardBody({ card }: { card: DebateCard }) {
  return (
    <>
      <CardField title="Identity">{card.identity}</CardField>
      {card.position ? (
        <CardField title="Position">{card.position}</CardField>
      ) : null}
      {card.reasoning.length > 0 ? (
        <CardField title="Reasoning">
          <ul className="m-0 pl-4">
            {card.reasoning.map((item, index) => (
              <li key={`${index}-${item}`}>{item}</li>
            ))}
          </ul>
        </CardField>
      ) : null}
      {card.speaking_style ? (
        <CardField title="Speaking style">{card.speaking_style}</CardField>
      ) : null}
      {card.voice_style ? (
        <CardField title="Voice">{card.voice_style}</CardField>
      ) : null}
      <div className="border-0 border-t-2 border-dashed border-[#111] pt-2">
        <strong className="text-[13px]">Dropped from AGENT.md</strong>
        {card.dropped.length === 0 ? (
          <p className="m-0 text-[13px] text-[#6B7280]">Nothing was dropped.</p>
        ) : (
          <ul className="m-0 mt-1 grid list-none gap-1.5 p-0">
            {card.dropped.map((item, index) => (
              <li
                className="grid gap-0.5 border-0 border-l-[3px] border-[#FFE14D] pl-2.5"
                key={`${index}-${item.excerpt}`}
              >
                <span className="text-[13px] font-bold">
                  {DROP_REASONS[item.reason]}
                </span>
                <small className="text-[13px] whitespace-pre-wrap text-[#6B7280]">
                  {item.excerpt}
                </small>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function CardField({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-0.5">
      <strong className="text-[13px]">{title}</strong>
      <div>{children}</div>
    </div>
  );
}
