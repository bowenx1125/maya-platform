/**
 * How a claim's retrieval outcome is graded, in one place.
 *
 * The backend records four `support_mode` values. A classroom needs three
 * ideas, and the score in the interaction panel needs the same three — so this
 * mapping lives here rather than twice, where the panel and the chart could
 * quietly disagree about what "direct" means.
 *
 * `no_match` is deliberately not folded into "indirect": retrieval found
 * nothing for that claim, and calling that indirect evidence would claim
 * support the debate never had.
 */
export type EvidenceSupportMode =
  "direct" | "contextual" | "general_reasoning" | "no_match";

export type EvidenceGrade = "direct" | "indirect" | "none";

/** Points awarded per graded claim when scoring an Agent. */
export const EVIDENCE_GRADE_POINTS: Record<EvidenceGrade, number> = {
  direct: 5,
  indirect: 2,
  none: 0,
};

export function evidenceGrade(
  mode: EvidenceSupportMode | string,
): EvidenceGrade {
  if (mode === "direct") return "direct";
  if (mode === "contextual") return "indirect";
  return "none";
}

/** Sum the points of one turn's evidence chain. */
export function gradeClaims(
  claims: readonly { support_mode: string }[],
): number {
  return claims.reduce(
    (total, claim) =>
      total + EVIDENCE_GRADE_POINTS[evidenceGrade(claim.support_mode)],
    0,
  );
}
