"use client";

import {
  EVIDENCE_GRADE_POINTS,
  gradeClaims,
  segmentEvidenceGrade,
} from "../../lib/evidence-grading";
import type { DebateParticipant, DebateTurn } from "../../lib/api";

function claimsOf(turn: DebateTurn): { support_mode: string }[] {
  // The chain is typed on the wire, but a turn from an older run may carry
  // none at all, so this reads defensively rather than asserting a shape.
  const trace: unknown = turn.evidence_trace;
  if (!Array.isArray(trace)) return [];
  const claims: { support_mode: string }[] = [];
  for (const row of trace as unknown[]) {
    if (!row || typeof row !== "object") continue;
    const mode = (row as { support_mode?: unknown }).support_mode;
    if (typeof mode === "string") claims.push({ support_mode: mode });
  }
  return claims;
}

export type AgentScoreRow = {
  id: string;
  label: string;
  color: string;
  value: number;
};

/** A1 life-point card tones (mock .sc --tone). */
const SCORE_TONES = ["#FFE14D", "#67E8F9", "#A3E635", "#F9A8D4", "#C4B5FD"];

/** Fixed 10 life dots as in A1-report mock; fill min(score, 10). */
const LIFE_MAX = 10;

export function agentScores(
  participants: DebateParticipant[],
  turns: DebateTurn[],
): AgentScoreRow[] {
  const byParticipant = new Map<string, number>();
  const seen = new Set<string>();
  for (const turn of turns) {
    if (seen.has(turn.id)) continue;
    seen.add(turn.id);
    const points = turn.segment_turn
      ? turn.segment_turn.segments.reduce((total, segment) => {
          const grade = segmentEvidenceGrade(segment);
          return total + (grade === null ? 0 : EVIDENCE_GRADE_POINTS[grade]);
        }, 0)
      : gradeClaims(claimsOf(turn));
    byParticipant.set(
      turn.participant_id,
      (byParticipant.get(turn.participant_id) ?? 0) + points,
    );
  }
  return participants
    .map((participant, index) => ({
      id: participant.id,
      label: participant.agent_name,
      color: SCORE_TONES[index % SCORE_TONES.length]!,
      value: byParticipant.get(participant.id) ?? 0,
    }))
    .sort((a, b) => b.value - a.value);
}

/**
 * A1 Report life-point scorecards (not the legacy Evaluation bar chart).
 * Scoring math stays in `agentScores`; only chrome changes.
 */
export function AgentScores({
  participants,
  turns,
}: {
  participants: DebateParticipant[];
  turns: DebateTurn[];
}) {
  const data = agentScores(participants, turns);
  return (
    <section
      aria-label="Evaluation"
      className="mr-9 mt-2 mb-4 grid grid-cols-3 gap-3 max-[600px]:mr-0 max-[600px]:grid-cols-1"
    >
      {data.length === 0 ? (
        <p className="col-span-full m-0 text-sm text-[#57534e]">
          No public speeches yet.
        </p>
      ) : (
        data.map((row) => {
          const filled = Math.max(0, Math.min(LIFE_MAX, Math.round(row.value)));
          return (
            <article
              key={row.id}
              className="rounded-[18px] border-[2.5px] border-solid border-[#111] px-3.5 py-3"
              style={{
                background: `color-mix(in srgb, ${row.color} 28%, #fff)`,
                boxShadow: `3px 4px 0 ${row.color}`,
              }}
            >
              <b className="mb-1 block font-[family-name:var(--font-lexend,Lexend,system-ui)] text-sm font-extrabold text-[#111]">
                {row.label}
              </b>
              <div className="my-0.5 mb-2 font-[family-name:var(--font-bricolage,var(--font-display),system-ui)] text-4xl leading-none font-extrabold text-[#111] tabular-nums">
                {row.value}
              </div>
              <div
                className="flex gap-[3px]"
                aria-hidden="true"
                data-testid="life-points"
              >
                {Array.from({ length: LIFE_MAX }, (_, i) => (
                  <i
                    key={i}
                    className={
                      i < filled
                        ? "block size-2.5 rounded-full border-2 border-solid border-[#111] bg-[#111]"
                        : "block size-2.5 rounded-full border-2 border-solid border-[#111] bg-white"
                    }
                  />
                ))}
              </div>
            </article>
          );
        })
      )}
    </section>
  );
}
