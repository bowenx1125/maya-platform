"use client";

import { BarChart, type ChartDatum } from "../charts";
import { useLocale } from "../locale";
import { EVIDENCE_GRADE_POINTS, gradeClaims } from "../../lib/evidence-grading";
import type { DebateParticipant, DebateTurn } from "../../lib/api";

/**
 * How much each Agent grounded its speeches in retrieved evidence.
 *
 * Read from the evidence chain the Check RAG panel already shows, through the
 * same `support_mode` mapping — one helper feeds both, so the score and the
 * labels can never disagree about what counts as direct.
 *
 * This measures how often a claim was tied to retrieved evidence. It is not a
 * judgement of how good an argument was, and the caption says so: the same
 * honesty the evidence panel keeps when it says it records lineage, not fact
 * checking.
 */

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
  for (const turn of turns) {
    const points = gradeClaims(claimsOf(turn));
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
  return (
    <section aria-labelledby="agent-scores-title" className="section-card">
      <div className="section-card-header">
        <div>
          <h2 id="agent-scores-title">{zh ? "Agent 评分" : "Agent scores"}</h2>
        </div>
      </div>
      <BarChart
        data={data}
        emptyLabel={zh ? "还没有公开发言。" : "No public speeches yet."}
      />
      <p className="muted-copy">
        {zh
          ? `直接证明 +${EVIDENCE_GRADE_POINTS.direct}，间接证明 +${EVIDENCE_GRADE_POINTS.indirect}，没有证据不计分。这是发言挂上检索证据的密度，不是论证质量的评判。`
          : `Direct evidence +${EVIDENCE_GRADE_POINTS.direct}, indirect +${EVIDENCE_GRADE_POINTS.indirect}, no evidence scores nothing. This counts how often a claim was tied to retrieved evidence, not how good an argument was.`}
      </p>
    </section>
  );
}
