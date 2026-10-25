"use client";

import { BarChart, type ChartDatum } from "../charts";
import { useT } from "../../lib/i18n";
import {
  EVIDENCE_GRADE_POINTS,
  EVIDENCE_GRADE_LABELS,
  gradeClaims,
  segmentEvidenceGrade,
} from "../../lib/evidence-grading";
import type { DebateParticipant, DebateTurn } from "../../lib/api";
import styles from "./agent-scores.module.css";
import panelStyles from "../report/report.module.css";

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
  return participants
    .map((participant, index) => ({
      id: participant.id,
      label: participant.agent_name,
      color: ["#9685b3", "#c3a366", "#789985", "#a28f7b", "#ac92ac"][index % 5],
      value: byParticipant.get(participant.id) ?? 0,
    }))
    .sort((a, b) => b.value - a.value);
}

export function AgentScores({
  participants,
  turns,
}: {
  participants: DebateParticipant[];
  turns: DebateTurn[];
}) {
  const data = agentScores(participants, turns);
  return (
    <section aria-labelledby="agent-scores-title" className={panelStyles.panel}>
      <div className={panelStyles.header}>
        <div>
          <h2 id="agent-scores-title">Evaluation</h2>
        </div>
      </div>
      <div className={panelStyles.content}>
        <div className={panelStyles.reportCard}>
          <div aria-label="Evidence grading" className={styles.legend}>
            {Object.entries(EVIDENCE_GRADE_LABELS).map(([grade, label]) => (
              <span key={grade} data-grade={grade}>
                {label}
              </span>
            ))}
          </div>
          <BarChart
            data={data}
            valueColor="var(--indigo-dark)"
            emptyLabel="No public speeches yet."
          />
        </div>
      </div>
    </section>
  );
}
