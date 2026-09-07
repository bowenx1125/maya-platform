import {
  EVIDENCE_GRADE_LABELS,
  segmentEvidenceGrade,
  type SegmentEvidence,
} from "../../lib/evidence-grading";
import styles from "./segment-grade.module.css";

export function SegmentGrade({ segment }: { segment: SegmentEvidence }) {
  const grade = segmentEvidenceGrade(segment);
  return (
    <span className={styles.grade} data-grade={grade ?? "unscored"}>
      {grade === null ? "Unscored" : EVIDENCE_GRADE_LABELS[grade]}
    </span>
  );
}
