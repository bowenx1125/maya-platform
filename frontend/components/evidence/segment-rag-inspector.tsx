"use client";

import { useLocale } from "../locale";
import type { SegmentEvidence } from "../../lib/evidence-grading";
import { SegmentGrade } from "./segment-grade";
import styles from "./segment-rag-inspector.module.css";

export type SegmentRagSegment = SegmentEvidence & {
  text: string;
  source_ids: readonly string[];
  reply_to: string | null;
};

export type SegmentRagSource = {
  source_id: string;
  source_filename: string;
  excerpt: string;
  query_text?: string | null;
  version_label: string;
};

function label(locale: string, en: string, zh: string): string {
  return locale === "zh" ? zh : en;
}

export function SegmentRagInspector({
  segments,
  sources,
}: {
  segments: readonly SegmentRagSegment[];
  sources: readonly SegmentRagSource[];
}) {
  const { locale } = useLocale();
  const sourceById = new Map(
    sources.map((source) => [source.source_id, source]),
  );
  const referencedSourceIds = new Set(
    segments.flatMap((segment) => segment.source_ids),
  );
  const unlinkedSources = sources.filter(
    (source) => !referencedSourceIds.has(source.source_id),
  );

  return (
    <details className={styles.inspector}>
      <summary>
        {label(locale, "Check RAG", "查看 RAG")}
        <span className={styles.count}>{sourceById.size}</span>
      </summary>
      <div className={styles.segmentList}>
        {segments.map((segment, index) => (
          <article className={styles.segment} key={`${index}-${segment.text}`}>
            <SegmentGrade segment={segment} />
            <p className={styles.segmentText}>{segment.text}</p>
            <div className={styles.sourceList}>
              {segment.source_ids.length === 0 ? (
                <span className={styles.noSource}>
                  {label(locale, "General reasoning", "一般推理")}
                </span>
              ) : (
                segment.source_ids.map((sourceId) => {
                  const source = sourceById.get(sourceId);
                  return source ? (
                    <SourceReceipt
                      key={source.source_id}
                      locale={locale}
                      source={source}
                    />
                  ) : (
                    <span className={styles.noSource} key={sourceId}>
                      {label(locale, "Source unavailable", "来源不可用")}
                    </span>
                  );
                })
              )}
            </div>
          </article>
        ))}
        {segments.length === 0
          ? unlinkedSources.map((source) => (
              <SourceReceipt
                key={source.source_id}
                locale={locale}
                source={source}
              />
            ))
          : null}
      </div>
    </details>
  );
}

function SourceReceipt({
  locale,
  source,
}: {
  locale: string;
  source: SegmentRagSource;
}) {
  return (
    <dl className={styles.source}>
      <div className={styles.sourceHeader}>
        <dt>{source.source_filename}</dt>
        <dd>{source.version_label}</dd>
      </div>
      <div>
        <dt>{label(locale, "Query", "检索问题")}</dt>
        <dd>{source.query_text ?? label(locale, "Not recorded", "未记录")}</dd>
      </div>
      <div>
        <dt>{label(locale, "Excerpt", "摘录")}</dt>
        <dd className={styles.excerpt}>{source.excerpt}</dd>
      </div>
    </dl>
  );
}
