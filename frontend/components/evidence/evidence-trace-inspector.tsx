"use client";

import {
  EVIDENCE_GRADE_POINTS,
  evidenceGrade,
} from "../../lib/evidence-grading";
import { useT } from "../../lib/i18n";

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
      <p
        className="m-0 text-[0.78rem] text-(--muted)"
        data-testid="evidence-trace-absent"
      >
        {all.length === 0
          ? "No snapshot evidence was cited in this turn."
          : `Evidence lineage recorded (${all.length}) but it no longer aligns with this speech.`}
      </p>
    );
  }

  return (
    <details
      className="mt-3 rounded-[12px] border border-(--line) bg-(--surface-subtle,#f5f5f7) px-[11px] py-[9px] [&_summary]:cursor-pointer [&_summary]:text-[0.84rem] [&_summary]:font-bold [&_summary]:text-(--indigo-dark)"
      data-testid="evidence-trace-inspector"
    >
      <summary>
        Check RAG{" "}
        <span className="ml-1 inline-grid size-[1.35rem] min-w-[1.35rem] place-items-center rounded-full bg-(--accent-soft,#f6ecd3) text-[0.72rem] text-(--indigo-dark)">
          {rows.length}
        </span>
      </summary>
      <ol className="mt-2.5 mb-0 grid list-none gap-2 p-0">
        {rows.map((row, index) => {
          const highlighted = speechSpanText(speech, row.speech_span);
          const hasSource = Boolean(
            row.source_filename && row.source_locator && row.evidence_id,
          );
          return (
            <li
              className="rounded-[10px] border border-(--line,#dedee3) bg-[rgba(255,255,255,0.66)] p-[9px]"
              data-support-mode={row.support_mode}
              key={`${row.claim_id}:${row.evidence_id ?? "none"}:${index}`}
            >
              <div className="flex flex-wrap items-baseline justify-between gap-1.5 text-[0.78rem] text-(--ink)">
                <strong>{claimTypeLabel(row.claim_type)}</strong>
                {/* The grade and what it is worth, in one pill: green for
                    direct, amber for indirect, plain for no evidence. The
                    number is the same one the Agent score sums. */}
                <span
                  className="inline-flex items-center gap-1.5 rounded-full border border-(--line) bg-(--panel) px-2.5 py-0.5 text-[0.74rem] text-(--muted) data-[grade=direct]:border-transparent data-[grade=direct]:bg-[rgba(45,138,104,0.14)] data-[grade=direct]:text-(--green) data-[grade=indirect]:border-transparent data-[grade=indirect]:bg-(--gold-soft) data-[grade=indirect]:text-(--ink,#1d1d1f)"
                  data-grade={evidenceGrade(row.support_mode)}
                >
                  {supportLabel(row.support_mode)}
                  <span className="font-bold">
                    +{EVIDENCE_GRADE_POINTS[evidenceGrade(row.support_mode)]}
                  </span>
                </span>
              </div>
              <p className="mt-2 mb-0 leading-[1.55] [&_mark]:rounded [&_mark]:bg-(--gold-soft) [&_mark]:px-[3px] [&_mark]:py-0.5 [&_mark]:text-(--ink)">
                <mark>{highlighted}</mark>
              </p>
              {row.query_text ? (
                <p className="mt-2 mb-0 text-[0.78rem] leading-[1.5] text-(--muted)">
                  <span className="mr-[5px] font-bold text-(--ink)">
                    Retrieval query
                  </span>
                  {queryKindLabel(row.query_kind)}
                </p>
              ) : null}
              {row.query_text ? (
                // The exact string that was embedded stays reachable: it is the
                // receipt for this retrieval, and the rows above are a reading
                // of it, not a replacement.
                <details className="mt-1 text-[0.78rem] text-(--muted) [&_summary]:cursor-pointer [&_p]:mt-1 [&_p]:mb-0 [&_p]:whitespace-pre-wrap">
                  <summary>Actual retrieval text</summary>
                  <p>{row.query_text}</p>
                </details>
              ) : null}
              {hasSource ? (
                <dl className="mt-2 mb-0 grid gap-[5px]">
                  <div className="grid grid-cols-[4.7rem_minmax(0,1fr)] gap-2">
                    <dt className="text-[0.74rem] text-(--muted)">Source</dt>
                    <dd className="m-0 text-[0.76rem] text-(--ink) [overflow-wrap:anywhere]">
                      {row.source_filename}
                    </dd>
                  </div>
                  <div className="grid grid-cols-[4.7rem_minmax(0,1fr)] gap-2">
                    <dt className="text-[0.74rem] text-(--muted)">Locator</dt>
                    <dd className="m-0 text-[0.76rem] text-(--ink) [overflow-wrap:anywhere]">
                      {row.source_locator}
                    </dd>
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
