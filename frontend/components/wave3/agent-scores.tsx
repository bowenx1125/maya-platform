"use client";

import { BarChart, type ChartDatum } from "../charts";
import { useLocale } from "../locale";
import {
  EVIDENCE_GRADE_POINTS,
  EVIDENCE_GRADE_LABELS,
  gradeClaims,
  segmentEvidenceGrade,
} from "../../lib/evidence-grading";
import type { DebateParticipant, DebateTurn } from "../../lib/api";
import styles from "./agent-scores.module.css";

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

export function agentScores(
  participants: DebateParticipant[],
  turns: DebateTurn[],
): ChartDatum[] {
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
  return participants.map((participant) => ({
    id: participant.id,
    label: `${participant.slot} · ${participant.agent_name}`,
    value: byParticipant.get(participant.id) ?? 0,
  }));
}

export function AgentScores({
  participants,
  turns,
}: {
  participants: DebateParticipant[];
  turns: DebateTurn[];
}) {
  const { locale } = useLocale();
  const zh = locale === "zh";
  const data = agentScores(participants, turns);
  const unscored = [...new Map(turns.map((turn) => [turn.id, turn])).values()]
    .flatMap((turn) => turn.segment_turn?.segments ?? [])
    .filter((segment) => segmentEvidenceGrade(segment) === null).length;
  return (
    <section aria-labelledby="agent-scores-title" className="section-card">
      <div className="section-card-header">
        <div>
          <h2 id="agent-scores-title">{zh ? "Agent 评分" : "Agent scores"}</h2>
        </div>
      </div>
      <div aria-label="Evidence grading" className={styles.legend}>
        {Object.entries(EVIDENCE_GRADE_LABELS).map(([grade, label]) => (
          <span key={grade} data-grade={grade}>
            {label}
          </span>
        ))}
        {unscored > 0 ? <span>{unscored} unscored</span> : null}
      </div>
      <BarChart
        data={data}
        emptyLabel={zh ? "还没有公开发言。" : "No public speeches yet."}
      />
    </section>
  );
}
