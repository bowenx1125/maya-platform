import {
  EVIDENCE_GRADE_LABELS,
  segmentEvidenceGrade,
  type SegmentEvidence,
} from "../../lib/evidence-grading";

export function SegmentGrade({ segment }: { segment: SegmentEvidence }) {
  const grade = segmentEvidenceGrade(segment) ?? "none";
  return (
    <span
      className="text-[0.78rem] font-[650] text-(--muted) data-[grade=direct]:text-(--green) data-[grade=indirect]:text-[#8d6926]"
      data-grade={grade}
    >
      {EVIDENCE_GRADE_LABELS[grade]}
    </span>
  );
}
