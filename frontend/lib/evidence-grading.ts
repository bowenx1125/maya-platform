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

export type SegmentEvidence = {
  source_ids: readonly string[];
  support_mode?: "direct" | "contextual" | "no_match" | null;
};

/** Older cited paragraphs did not record a grade; never invent one. */
export function segmentEvidenceGrade(
  segment: SegmentEvidence,
): EvidenceGrade | null {
  if (!segment.support_mode) return null;
  if (segment.source_ids.length === 0) {
    return segment.support_mode === "no_match" ? "none" : null;
  }
  if (segment.support_mode === "direct") return "direct";
  if (segment.support_mode === "contextual") return "indirect";
  return null;
}

export const EVIDENCE_GRADE_LABELS: Record<EvidenceGrade, string> = {
  direct: "Direct evidence +5",
  indirect: "Indirect evidence +2",
  none: "No match +0",
};

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
