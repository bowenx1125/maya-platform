"use client";

import { useLocale } from "../locale";
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

type TextPair = { en: string; zh: string };

function label(locale: string, value: TextPair): string {
  return locale === "zh" ? value.zh : value.en;
}

function supportLabel(locale: string, mode: EvidenceTraceSupportMode): string {
  if (mode === "direct") {
    return label(locale, { en: "Supports directly", zh: "直接支持" });
  }
  if (mode === "contextual") {
    return label(locale, { en: "Used as context", zh: "作为背景使用" });
  }
  if (mode === "no_match") {
    return label(locale, {
      en: "No relevant evidence found; general reasoning",
      zh: "未找到相关证据；这是一般推理",
    });
  }
  return label(locale, {
    en: "General reasoning",
    zh: "一般推理",
  });
}

function claimTypeLabel(locale: string, type: EvidenceTraceClaimType): string {
  const values: Record<EvidenceTraceClaimType, TextPair> = {
    factual: { en: "Factual", zh: "事实" },
    background: { en: "Background", zh: "背景" },
    value_judgement: { en: "Value judgement", zh: "价值判断" },
    proposal: { en: "Proposal", zh: "建议" },
  };
  return label(locale, values[type]);
}

export function EvidenceTraceInspector({
  speech,
  trace,
}: {
  speech: string;
  trace?: unknown;
}) {
  const { locale } = useLocale();
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
          ? label(locale, {
              en: "No snapshot evidence was cited in this turn.",
              zh: "本轮发言没有引用快照证据。",
            })
          : label(locale, {
              en: `Evidence lineage recorded (${all.length}) but it no longer aligns with this speech.`,
              zh: `记录了 ${all.length} 条证据链，但与本段发言对不上。`,
            })}
      </p>
    );
  }

  return (
    <details
      className={styles.inspector}
      data-testid="evidence-trace-inspector"
    >
      <summary>
        {label(locale, {
          en: "Inspect claim evidence lineage",
          zh: "查看观点证据链",
        })}{" "}
        <span className={styles.count}>{rows.length}</span>
      </summary>
      <p className={styles.disclaimer}>
        {label(locale, {
          en: "This records generation lineage, not fact checking.",
          zh: "这里记录生成来源链路，不代表事实核验。",
        })}
      </p>
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
                <strong>{claimTypeLabel(locale, row.claim_type)}</strong>
                <span className={styles.mode}>
                  {supportLabel(locale, row.support_mode)}
                </span>
              </div>
              <p className={styles.highlightedSpeech}>
                <mark>{highlighted}</mark>
              </p>
              {row.query_text ? (
                <p className={styles.detail}>
                  <span className={styles.detailLabel}>
                    {label(locale, { en: "Retrieval query", zh: "检索问题" })}
                  </span>
                  {row.query_text}
                </p>
              ) : null}
              {hasSource ? (
                <dl className={styles.source}>
                  <div>
                    <dt>{label(locale, { en: "Source", zh: "来源" })}</dt>
                    <dd>{row.source_filename}</dd>
                  </div>
                  <div>
                    <dt>{label(locale, { en: "Locator", zh: "定位" })}</dt>
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
