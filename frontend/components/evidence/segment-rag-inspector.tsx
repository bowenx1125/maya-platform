"use client";

import { useT } from "../../lib/i18n";
import type { SegmentEvidence } from "../../lib/evidence-grading";
import { SegmentGrade } from "./segment-grade";

export type SegmentRagSegment = SegmentEvidence & {
  text: string;
  source_ids: readonly string[];
  reply_to: string | null;
  reply_text?: string | null;
};

export type SegmentRagSource = {
  source_id: string;
  source_filename: string;
  excerpt: string;
  query_text?: string | null;
  version_label: string;
};

export function SegmentRagInspector({
  segments,
  sources,
}: {
  segments: readonly SegmentRagSegment[];
  sources: readonly SegmentRagSource[];
}) {
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
    <details className="mt-3 rounded-[12px] border border-(--line) bg-(--surface-subtle,#f5f5f7) px-[11px] py-[9px] [&_summary]:cursor-pointer [&_summary]:text-[0.84rem] [&_summary]:font-bold [&_summary]:text-(--indigo-dark)">
      <summary>
        Check RAG
        <span className="ml-1.5 inline-grid size-[1.35rem] min-w-[1.35rem] place-items-center rounded-full bg-(--accent-soft,#f6ecd3) text-[0.72rem] text-(--indigo-dark)">{sourceById.size}</span>
      </summary>
      <div className="mt-2.5 grid gap-2.5">
        {segments.map((segment, index) => (
          <article className="grid min-w-0 gap-[7px] border-l-[3px] border-(--gold) pl-2.5" key={`${index}-${segment.text}`}>
            <SegmentGrade segment={segment} />
            <p className="m-0 text-[0.85rem] leading-[1.55] whitespace-pre-wrap text-(--ink) [overflow-wrap:anywhere]">{segment.text}</p>
            <div className="grid gap-[7px]">
              {segment.source_ids.length === 0 ? (
                <span className="text-[0.78rem] text-(--muted)">General reasoning</span>
              ) : (
                segment.source_ids.map((sourceId) => {
                  const source = sourceById.get(sourceId);
                  return source ? (
                    <SourceReceipt key={source.source_id} source={source} />
                  ) : (
                    <span className="text-[0.78rem] text-(--muted)" key={sourceId}>
                      Source unavailable
                    </span>
                  );
                })
              )}
            </div>
          </article>
        ))}
        {segments.length === 0
          ? unlinkedSources.map((source) => (
              <SourceReceipt key={source.source_id} source={source} />
            ))
          : null}
      </div>
    </details>
  );
}

function SourceReceipt({ source }: { source: SegmentRagSource }) {
  return (
    <dl className="m-0 grid min-w-0 gap-[5px] rounded-[10px] border border-(--line,#dedee3) bg-[rgba(255,255,255,0.72)] p-[9px]">
      <div className="grid min-w-0 grid-cols-[4.7rem_minmax(0,1fr)] gap-2 max-[620px]:grid-cols-1 max-[620px]:gap-0.5 items-baseline">
        <dt className="text-[0.74rem] font-[750] text-(--ink) [overflow-wrap:anywhere]">{source.source_filename}</dt>
        <dd className="m-0 min-w-0 text-[0.76rem] leading-[1.45] text-(--ink) [overflow-wrap:anywhere]">{source.version_label}</dd>
      </div>
      <div className="grid min-w-0 grid-cols-[4.7rem_minmax(0,1fr)] gap-2 max-[620px]:grid-cols-1 max-[620px]:gap-0.5">
        <dt className="text-[0.74rem] font-[650] text-(--muted)">Query</dt>
        <dd className="m-0 min-w-0 text-[0.76rem] leading-[1.45] text-(--ink) [overflow-wrap:anywhere]">{source.query_text ?? "Not recorded"}</dd>
      </div>
      <div className="grid min-w-0 grid-cols-[4.7rem_minmax(0,1fr)] gap-2 max-[620px]:grid-cols-1 max-[620px]:gap-0.5">
        <dt className="text-[0.74rem] font-[650] text-(--muted)">Excerpt</dt>
        <dd className="m-0 min-w-0 text-[0.76rem] leading-[1.45] whitespace-pre-wrap text-(--ink) [overflow-wrap:anywhere]">{source.excerpt}</dd>
      </div>
    </dl>
  );
}
