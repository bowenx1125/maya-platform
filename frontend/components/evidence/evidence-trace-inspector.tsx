"use client";

import {
  EVIDENCE_GRADE_POINTS,
  evidenceGrade,
} from "../../lib/evidence-grading";
import { useT } from "../../lib/i18n";
import styles from "./evidence-trace-inspector.module.css";

export type EvidenceTraceClaimType =
  "factual" | "background" | "value_judgement" | "proposal";
export type EvidenceTraceSupportMode =
  "direct" | "contextual" | "general_reasoning" | "no_match";

export type EvidenceTraceRow = {
  trace_version: "evidence_trace_v1";
  turn_id: string;
  claim_id: string;
  claim_text: string;
  claim_type: EvidenceTraceClaimType;
  query_id?: string | null;
  query_kind?: string | null;
  query_text?: string | null;
  evidence_id?: string | null;
  chunk_id?: string | null;
  source_filename?: string | null;
  source_locator?: string | null;
  support_mode: EvidenceTraceSupportMode;
  speech_span: {
    start_utf16: number;
    end_utf16: number;
  };
};

type RecordValue = Record<string, unknown>;

function isRecord(value: unknown): value is RecordValue {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

const CLAIM_TYPES: readonly EvidenceTraceClaimType[] = [
  "factual",
  "background",
  "value_judgement",
  "proposal",
];
const SUPPORT_MODES: readonly EvidenceTraceSupportMode[] = [
  "direct",
  "contextual",
  "general_reasoning",
  "no_match",
];

/**
 * Keep the browser projection defensive. The server remains authoritative and
 * rejects malformed rows; the UI simply omits a row it cannot safely explain.
 */
export function normaliseEvidenceTrace(value: unknown): EvidenceTraceRow[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isRecord(item) || item.trace_version !== "evidence_trace_v1")
      return [];
    const span = item.speech_span;
    if (
      !nonEmptyString(item.turn_id) ||
      !nonEmptyString(item.claim_id) ||
      !nonEmptyString(item.claim_text) ||
      !CLAIM_TYPES.includes(item.claim_type as EvidenceTraceClaimType) ||
      !SUPPORT_MODES.includes(item.support_mode as EvidenceTraceSupportMode) ||
      !isRecord(span) ||
      !nonNegativeInteger(span.start_utf16) ||
      !nonNegativeInteger(span.end_utf16) ||
      span.end_utf16 <= span.start_utf16
    ) {
      return [];
    }
    const optional = (name: string): string | null =>
      nonEmptyString(item[name]) ? item[name] : null;
    return [
      {
        trace_version: "evidence_trace_v1",
        turn_id: item.turn_id,
        claim_id: item.claim_id,
        claim_text: item.claim_text,
        claim_type: item.claim_type as EvidenceTraceClaimType,
        query_id: optional("query_id"),
        query_kind: optional("query_kind"),
        query_text: optional("query_text"),
        evidence_id: optional("evidence_id"),
        chunk_id: optional("chunk_id"),
        source_filename: optional("source_filename"),
        source_locator: optional("source_locator"),
        support_mode: item.support_mode as EvidenceTraceSupportMode,
        speech_span: {
          start_utf16: span.start_utf16,
          end_utf16: span.end_utf16,
        },
      },
    ];
  });
}

/** JavaScript string offsets are UTF-16 code units, matching the API contract. */
export function speechSpanText(
  speech: string,
  span: EvidenceTraceRow["speech_span"],
): string {
  return speech.slice(span.start_utf16, span.end_utf16);
}

function supportLabel(mode: EvidenceTraceSupportMode): string {
  const grade = evidenceGrade(mode);
  if (grade === "direct") {
    return "Direct evidence";
  }
  if (grade === "indirect") {
    return "Indirect evidence";
  }
  // `no_match` and general reasoning share this: retrieval returned nothing
  // this claim could stand on. Folding it into "indirect" would claim support
  // the debate never had.
  return "No evidence";
}

/**
 * What the retrieval was asking for.
 *
 * The query kind is a stable enum; the query text is the exact string that was
 * embedded, and it opens with the topic and an instruction, so printing it
 * whole told a reader almost nothing about which question this row answers.
 */
function queryKindLabel(kind: string | null | undefined) {
  if (kind === "pending_question") {
    return "Answering a question";
  }
  if (kind === "rebuttal") {
    return "Engaging an earlier claim";
  }
  if (kind === "updated_position") {
    return "Updated position";
  }
  return "Independent viewpoint";
}

function claimTypeLabel(type: EvidenceTraceClaimType): string {
  const values: Record<EvidenceTraceClaimType, string> = {
    factual: "Factual",
    background: "Background",
    value_judgement: "Value judgement",
    proposal: "Proposal",
  };
  return values[type];
}

export function EvidenceTraceInspector({
  speech,
  trace,
}: {
  speech: string;
  trace?: unknown;
}) {
  const all = normaliseEvidenceTrace(trace);
  // A span that does not reproduce its claim is not shown as lineage: an
  // unverifiable highlight is worse than none. But dropping every row used to
  // render nothing at all, which left a teacher unable to tell "this turn cited
  // no evidence" from "its lineage no longer lines up with the speech".
  const rows = all.filter(
    (row) =>
      row.speech_span.end_utf16 <= speech.length &&
      speechSpanText(speech, row.speech_span) === row.claim_text,
  );
  if (rows.length === 0) {
    return (
      <p className={styles.absent} data-testid="evidence-trace-absent">
        {all.length === 0
          ? "No snapshot evidence was cited in this turn."
          : `Evidence lineage recorded (${all.length}) but it no longer aligns with this speech.`}
      </p>
    );
  }

  return (
    <details
      className={styles.inspector}
      data-testid="evidence-trace-inspector"
    >
      <summary>
        Check RAG <span className={styles.count}>{rows.length}</span>
      </summary>
      <ol className={styles.claimList}>
        {rows.map((row, index) => {
          const highlighted = speechSpanText(speech, row.speech_span);
          const hasSource = Boolean(
            row.source_filename && row.source_locator && row.evidence_id,
          );
          return (
            <li
              className={styles.claim}
              data-support-mode={row.support_mode}
              key={`${row.claim_id}:${row.evidence_id ?? "none"}:${index}`}
            >
              <div className={styles.claimHeader}>
                <strong>{claimTypeLabel(row.claim_type)}</strong>
                {/* The grade and what it is worth, in one pill: green for
                    direct, amber for indirect, plain for no evidence. The
                    number is the same one the Agent score sums. */}
                <span
                  className={styles.mode}
                  data-grade={evidenceGrade(row.support_mode)}
                >
                  {supportLabel(row.support_mode)}
                  <span className={styles.modeScore}>
                    +{EVIDENCE_GRADE_POINTS[evidenceGrade(row.support_mode)]}
                  </span>
                </span>
              </div>
              <p className={styles.highlightedSpeech}>
                <mark>{highlighted}</mark>
              </p>
              {row.query_text ? (
                <p className={styles.detail}>
                  <span className={styles.detailLabel}>Retrieval query</span>
                  {queryKindLabel(row.query_kind)}
                </p>
              ) : null}
              {row.query_text ? (
                // The exact string that was embedded stays reachable: it is the
                // receipt for this retrieval, and the rows above are a reading
                // of it, not a replacement.
                <details className={styles.rawQuery}>
                  <summary>Actual retrieval text</summary>
                  <p>{row.query_text}</p>
                </details>
              ) : null}
              {hasSource ? (
                <dl className={styles.source}>
                  <div>
                    <dt>Source</dt>
                    <dd>{row.source_filename}</dd>
                  </div>
                  <div>
                    <dt>Locator</dt>
                    <dd>{row.source_locator}</dd>
                  </div>
                </dl>
              ) : null}
            </li>
          );
        })}
      </ol>
    </details>
  );
}
