"use client";

import type { ReactNode } from "react";

import type {
  AgentDiagnostic,
  DebateDiagnostics,
  ParagraphDiagnostic,
  RoundDiagnostic,
} from "../../../lib/api/debate-diagnostics";
import { teachingRoundLabel } from "../../../lib/debate-rounds";
import { cn } from "../../../lib/utils";
import { IconEye } from "../../quiet-icons";
import {
  DEBATE_BUTTON,
  DEBATE_PAGE,
  DEBATE_TAG,
  DEBATE_TAG_TONE,
  PREVIEW_TAPE,
  PREVIEW_TONES,
  PREVIEW_TURN,
} from "../debate-chrome";

const PAGE_HELP =
  "How each Agent used its own material. Retrieved: chunks the server fetched from the Agent's RAG, distinct over total. Traced: share of the speech's three-word (Chinese: three-character) runs found in the chunks its paragraphs cite. Quoted, Paraphrased and Not found are measured by the server; the model's own label is shown beside them. These numbers never change a speech or a Report score.";

const SELF_LABEL: Record<
  NonNullable<ParagraphDiagnostic["self_label"]>,
  string
> = {
  direct: "Direct",
  contextual: "Contextual",
  no_match: "No match",
};

const SERVER_LABEL: Record<
  NonNullable<ParagraphDiagnostic["grounding_class"]>,
  string
> = {
  quoted: "Quoted",
  paraphrased: "Paraphrased",
  not_found: "Not found",
  other_language: "Source in another language, not measured",
};

const STAT =
  "inline-flex items-center gap-1 rounded-full border-2 border-[#111] bg-white px-2.5 py-[3px] font-body text-xs leading-[normal] font-bold whitespace-nowrap text-[#111]";

function percent(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "—"
    : `${Math.round(value * 100)}%`;
}

function unitName(unit: DebateDiagnostics["unit"]): string {
  return unit === "han_chars" ? "Han chars" : "words";
}

export function DebateDiagnosticsView({
  topic,
  diagnostics,
  agentSlot,
}: {
  topic?: string;
  diagnostics: DebateDiagnostics;
  /** Mount point for a later per-Agent summary (a debate card); unused today. */
  agentSlot?: (agent: AgentDiagnostic) => ReactNode;
}) {
  const unit = unitName(diagnostics.unit);
  return (
    <div className={DEBATE_PAGE}>
      <div className={PREVIEW_TAPE} data-testid="debate-diagnostics">
        <h1
          className="m-0 w-fit max-w-none min-w-0 font-display text-[26px] leading-[normal] font-bold max-[600px]:text-xl"
          data-ui-guide="debate.diagnostics"
          data-ui-guide-text={PAGE_HELP}
          tabIndex={0}
        >
          {topic ? `${topic} · Diagnostics` : "Diagnostics"}
        </h1>
        <div className="mt-4 grid gap-3">
          {diagnostics.agents.length === 0 ? (
            <p className="m-0 font-body text-sm text-[#6B7280]">
              No Agents in this Debate.
            </p>
          ) : null}
          {diagnostics.agents.map((agent, index) => (
            <AgentCard
              key={agent.participant_id}
              agent={agent}
              unit={unit}
              tone={PREVIEW_TONES[index % PREVIEW_TONES.length]}
              slot={agentSlot?.(agent)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function AgentCard({
  agent,
  unit,
  tone,
  slot,
}: {
  agent: AgentDiagnostic;
  unit: string;
  tone: string;
  slot?: ReactNode;
}) {
  const oneChunk = agent.retrievals > 1 && agent.distinct_chunks === 1;
  const counts = agent.grounding_counts;
  return (
    <article
      className={PREVIEW_TURN}
      style={{ "--tone": tone } as React.CSSProperties}
      data-testid={`diagnostics-agent-${agent.participant_id}`}
    >
      <div className="flex items-center gap-2.5">
        <span className="rounded-full border-2 border-[#111] bg-(--tone) px-[7px] py-0.5 font-body text-[11px] leading-[normal] font-extrabold text-[#111]">
          {agent.slot}
        </span>
        <h2 className="m-0 min-w-0 font-display text-base leading-[normal] font-bold">
          {agent.agent_name}
        </h2>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5" data-testid="agent-stats">
        <span className={STAT}>
          Agent.md{" "}
          {agent.agent_md_chars === null
            ? "not kept"
            : `${agent.agent_md_chars.toLocaleString("en")} chars`}
        </span>
        <span className={STAT}>
          RAG {agent.knowledge_documents} doc
          {agent.knowledge_documents === 1 ? "" : "s"} ·{" "}
          {agent.knowledge_chunks} chunk
          {agent.knowledge_chunks === 1 ? "" : "s"}
        </span>
        <span
          className={cn(
            STAT,
            "max-w-full whitespace-normal",
            oneChunk && DEBATE_TAG_TONE.thinking,
          )}
          data-testid="agent-retrieved"
        >
          Retrieved {agent.distinct_chunks} distinct / {agent.retrievals}
          {oneChunk ? " · same chunk every time" : ""}
        </span>
        <span className={STAT}>Cited {agent.cited_chunks}</span>
        <span className={STAT} data-testid="agent-traced">
          Traced {percent(agent.traced_share)}
        </span>
        <span className={STAT}>
          Quoted {counts.quoted} · Paraphrased {counts.paraphrased} · Not found{" "}
          {counts.not_found}
        </span>
        {counts.other_language > 0 ? (
          <span className={STAT} data-testid="agent-other-language">
            {counts.other_language} not measured: source in another language
          </span>
        ) : null}
      </div>

      {slot ? (
        <div className="mt-2" data-slot="debate-card">
          {slot}
        </div>
      ) : null}

      {agent.rounds.length === 0 ? (
        <p className="mt-2 mb-0 font-body text-sm text-[#6B7280] italic">
          No generated speech yet.
        </p>
      ) : (
        <details className="mt-2.5 border-0 border-t-2 border-dashed border-[#111] pt-2.5 font-body [&_summary]:min-h-0 [&_summary]:p-0">
          <summary
            className={cn(
              DEBATE_BUTTON,
              "list-none py-1 pr-2.5 pl-2 text-xs leading-[normal] [&::-webkit-details-marker]:hidden",
            )}
            data-testid="diagnostics-rounds"
          >
            <IconEye size={18} />
            <span>Rounds</span>
            <span className="ml-0.5 inline-grid h-[1.35rem] min-w-[1.35rem] place-items-center rounded-full border-2 border-[#111] bg-[#FFE14D] text-[11px] font-extrabold">
              {agent.rounds.length}
            </span>
          </summary>
          <div className="mt-2.5 grid gap-2.5">
            {agent.rounds.map((round) => (
              <RoundRow key={round.turn_id} round={round} unit={unit} />
            ))}
          </div>
        </details>
      )}
    </article>
  );
}

function RoundRow({ round, unit }: { round: RoundDiagnostic; unit: string }) {
  const over = round.unit_cap !== null && round.speech_units > round.unit_cap;
  return (
    <div
      className="grid min-w-0 gap-2 border-0 border-l-[3px] border-[#FFE14D] pl-2.5 text-[13px] leading-[1.45]"
      data-testid={`diagnostics-round-${round.turn_id}`}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <strong>
          Round {round.round_no}
          {teachingRoundLabel(round.round_no, "en")
            ? ` · ${teachingRoundLabel(round.round_no, "en")}`
            : ""}
        </strong>
        <span className={cn(DEBATE_TAG, over && DEBATE_TAG_TONE.thinking)}>
          {round.unit_cap === null
            ? `${round.speech_units} ${unit}`
            : `${round.speech_units} / ${round.unit_cap} ${unit}`}
        </span>
        {round.repaired ? (
          <span className={cn(DEBATE_TAG, DEBATE_TAG_TONE.thinking)}>
            Repaired
          </span>
        ) : null}
        <span className={DEBATE_TAG}>Traced {percent(round.traced_share)}</span>
        {round.repeats_earlier_share !== null ? (
          <span className={DEBATE_TAG}>
            Repeats earlier {percent(round.repeats_earlier_share)}
          </span>
        ) : null}
      </div>

      <div className="grid gap-1">
        <span className="font-bold">Retrieved</span>
        {round.retrieved.length === 0 ? (
          <span className="text-[#6B7280]">Nothing retrieved.</span>
        ) : (
          <ul className="m-0 grid list-none gap-1 p-0">
            {round.retrieved.map((chunk, index) => (
              <li
                className="flex min-w-0 flex-wrap items-center gap-x-2 [overflow-wrap:anywhere]"
                key={`${chunk.chunk_id}-${index}`}
              >
                <span className="font-medium">{chunk.source_filename}</span>
                <span className="text-[#6B7280]">
                  rank {chunk.rank} · score {chunk.score.toFixed(2)} ·{" "}
                  {chunk.chunk_chars.toLocaleString("en")} chars
                </span>
                {chunk.cited ? (
                  <span className={cn(DEBATE_TAG, DEBATE_TAG_TONE.ready)}>
                    Cited
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      {round.paragraphs === null ? (
        <span className="text-[#6B7280]">
          Paragraphs were not stored for this turn.
        </span>
      ) : (
        <div className="grid gap-1">
          <span className="font-bold">Paragraphs</span>
          <ol className="m-0 grid gap-1 pl-5">
            {round.paragraphs.map((paragraph, index) => (
              <li key={index} data-testid="diagnostics-paragraph">
                {paragraph.units} {unit} · Model:{" "}
                {paragraph.self_label
                  ? SELF_LABEL[paragraph.self_label]
                  : "none recorded"}{" "}
                · Server:{" "}
                {paragraph.grounding_class
                  ? paragraph.grounding_class === "other_language"
                    ? SERVER_LABEL.other_language
                    : `${SERVER_LABEL[paragraph.grounding_class]} (${percent(paragraph.coverage)})`
                  : "no source cited"}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
