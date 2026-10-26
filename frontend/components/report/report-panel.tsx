"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DismissibleAlert } from "../dismissible-alert";
import type { components } from "../../lib/api/generated/schema";
import { apiErrorMessage, type IdempotencyHandle } from "../../lib/api";
import { useIdempotencyStore } from "../../lib/idempotency";
import { nextPollDelay } from "../../lib/poll-pacing";
import { useT } from "../../lib/i18n";
import {
  cleanReportCitations,
  reportLengthUnit,
} from "../../lib/report-citations";
import { ReportMarkdown } from "./report-markdown";

export type Report = components["schemas"]["Report"];
export type ReportRevision = components["schemas"]["ReportRevision"];
export type ReportRevisionSummary =
  components["schemas"]["ReportRevisionSummary"];

export type ReportDownload = {
  content: string;
  filename: string;
};

/**
 * The panel consumes this narrow platform boundary.  ``PlatformApi`` can
 * implement these methods directly, while teacher pages may pass a small
 * adapter during the staged Wave 3 integration.  No provider or raw HTML
 * contract enters this component.
 */
export type ReportPanelApi = {
  getCurrentReport: (debateId: string) => Promise<Report>;
  regenerateReport: (
    debateId: string,
    options?: { idempotency?: IdempotencyHandle },
  ) => Promise<Report>;
  listReportRevisions: (debateId: string) => Promise<ReportRevisionSummary[]>;
  getReportRevision: (
    debateId: string,
    revisionId: string,
  ) => Promise<ReportRevision>;
  downloadCurrentReport: (
    debateId: string,
    language?: "en",
  ) => Promise<ReportDownload>;
};

export type ReportPanelProps = {
  debateId: string;
  api: ReportPanelApi;
  canRegenerate?: boolean;
};

const REPORT_POLL_INTERVAL_MS = 1500;
const REPORT_POLL_LIMIT_MS = 180_000;

function reportStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    not_started: "Not started",
    generating: "Generating",
    ready: "Ready",
    failed: "Failed",
  };
  return labels[status] ?? status;
}

function revisionTitle(revision: number): string {
  return `Version ${revision}`;
}

function triggerDownload(content: string, filename: string): void {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noreferrer";
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function ReportPanel({
  debateId,
  api,
  canRegenerate = true,
}: ReportPanelProps) {
  const idempotency = useIdempotencyStore();
  const [report, setReport] = useState<Report | null>(null);
  const [revisions, setRevisions] = useState<ReportRevisionSummary[]>([]);
  const [selectedRevision, setSelectedRevision] =
    useState<ReportRevision | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollTimedOut, setPollTimedOut] = useState(false);
  const pollStartedAt = useRef<number | null>(null);
  const loadVersion = useRef(0);

  const copy = {
    title: "Report",
    insight: "Anonymous classroom insight",
    report: "Current report",
    history: "History",
    regenerate: "Regenerate",
    download: "Download",
    noHistory: "No report versions yet.",
    view: "Review",
    selected: "Viewing",
    generating: "Generating report...",
    failed: "Report generation failed; earlier revisions remain.",
    included: "included",
    filtered: "filtered",
    words: reportLengthUnit("en"),
  };

  const load = useCallback(
    async ({ quiet = false } = {}) => {
      const version = ++loadVersion.current;
      if (!quiet) setLoading(true);
      if (!quiet) setPollTimedOut(false);
      setError(null);
      const loadRevisions = () => {
        // History is supplementary; its failure must not hide a completed report
        // or prevent the authoritative status from continuing to poll.
        void api.listReportRevisions(debateId).then(
          (nextRevisions) => {
            if (loadVersion.current === version) setRevisions(nextRevisions);
          },
          (cause: unknown) => {
            if (loadVersion.current === version)
              setError(apiErrorMessage(cause));
          },
        );
      };
      if (!quiet) loadRevisions();
      try {
        const nextReport = await api.getCurrentReport(debateId);
        if (loadVersion.current !== version) return;
        setReport(nextReport);
        if (!quiet) setSelectedRevision(null);
        if (
          nextReport.generation_status !== "generating" &&
          nextReport.insight.status !== "generating"
        ) {
          setPollTimedOut(false);
          if (quiet) loadRevisions();
        }
      } catch (cause) {
        if (loadVersion.current === version) setError(apiErrorMessage(cause));
      } finally {
        if (loadVersion.current === version) setLoading(false);
      }
    },
    [api, debateId],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => {
      window.clearTimeout(timer);
      loadVersion.current += 1;
    };
  }, [load]);

  useEffect(() => {
    const generating =
      report?.generation_status === "generating" ||
      report?.insight.status === "generating";
    if (!generating || pollTimedOut) {
      if (!generating) pollStartedAt.current = null;
      return;
    }

    let disposed = false;
    let timer: number | null = null;
    const startedAt = pollStartedAt.current ?? Date.now();
    pollStartedAt.current = startedAt;
    const deadline = startedAt + REPORT_POLL_LIMIT_MS;
    let attempt = 0;
    const poll = async () => {
      if (disposed) return;
      if (Date.now() >= deadline) {
        pollStartedAt.current = null;
        setPollTimedOut(true);
        return;
      }
      await load({ quiet: true });
      if (!disposed) {
        // 5-10 s while the server is busy (lib/poll-pacing.ts).
        timer = window.setTimeout(
          () => void poll(),
          nextPollDelay(REPORT_POLL_INTERVAL_MS, attempt++),
        );
      }
    };
    timer = window.setTimeout(() => void poll(), REPORT_POLL_INTERVAL_MS);
    return () => {
      disposed = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [load, pollTimedOut, report?.generation_status, report?.insight.status]);

  async function regenerate() {
    setBusy(true);
    setError(null);
    const intent = `report.generate:${debateId}`;
    const handle = idempotency.handleFor(intent);
    try {
      await api.regenerateReport(debateId, { idempotency: handle });
      idempotency.finish(intent, handle);
      await load();
    } catch (cause) {
      setError(apiErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.downloadCurrentReport(debateId, "en");
      triggerDownload(cleanReportCitations(result.content), result.filename);
    } catch (cause) {
      setError(apiErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function selectRevision(revisionId: string) {
    setBusy(true);
    setError(null);
    try {
      setSelectedRevision(await api.getReportRevision(debateId, revisionId));
    } catch (cause) {
      setError(apiErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  const insight = report?.insight;
  const current = report?.current_success_revision ?? null;
  const displayed = selectedRevision ?? current;
  const insightGenerating = insight?.status === "generating";
  const reportGenerating = report?.generation_status === "generating";
  const polling = insightGenerating || reportGenerating;

  return (
    <section
      className="grid min-w-0 gap-(--section-content-gap) rounded-[22px] border border-(--line,#dedee3) bg-white p-(--workspace-inset)"
      aria-busy={loading || polling}
      data-report-status={report?.generation_status ?? "not_started"}
      data-insight-status={insight?.status ?? "not_started"}
    >
      <header className="flex items-start justify-between gap-4 border-b border-(--line,#dedee3) pb-(--section-content-gap)">
        <div>
          <h2 className="m-0 text-[1.24rem] leading-[1.4] text-(--indigo-dark)">
            {copy.title}
          </h2>
        </div>
      </header>

      <div className="grid min-w-0 gap-(--section-content-gap) rounded-[14px] border border-transparent bg-(--surface-subtle,#f5f5f7) p-4">
        {error ? (
          <DismissibleAlert className="mt-2 rounded-[0.7rem] bg-[#fff0ee] px-[0.85rem] py-[0.7rem] leading-[1.55] text-[#a34842]">
            {error}
          </DismissibleAlert>
        ) : null}

        {pollTimedOut && polling ? (
          <p
            className="mt-2 rounded-[0.7rem] bg-[#fff8ec] px-[0.85rem] py-[0.7rem] leading-[1.55] text-[#8b6532]"
            role="status"
          >
            The report is still generating. Reopen this page later.
          </p>
        ) : null}
        {report?.generation_status === "failed" ||
        insight?.status === "failed" ? (
          <DismissibleAlert
            className="mt-2 rounded-[0.7rem] bg-[#fff8ec] px-[0.85rem] py-[0.7rem] leading-[1.55] text-[#8b6532]"
            role="status"
          >
            {copy.failed}
          </DismissibleAlert>
        ) : null}

        {insight?.items.length ? (
          <ul
            className="m-0 grid list-none gap-2 p-0"
            aria-label={copy.insight}
          >
            {insight.items.map((item, index) => (
              <li
                key={`${item.category}-${item.summary}-${index}`}
                className="grid grid-cols-[auto_1fr_auto] items-center gap-[0.65rem] rounded-[0.7rem] border border-[rgba(24,39,61,0.1)] px-[0.8rem] py-[0.65rem]"
              >
                <span className="text-[0.78rem] font-bold uppercase text-(--muted,#62626a)">
                  {item.category}
                </span>
                <p className="m-0 min-w-0 [overflow-wrap:anywhere]">
                  {item.summary}
                </p>
                <strong>{item.count}</strong>
              </li>
            ))}
          </ul>
        ) : null}

        <div className="min-w-0 border-0 bg-transparent p-0">
          <div className="flex items-start justify-between gap-4 max-[680px]:flex-wrap max-[680px]:gap-2">
            {displayed ? (
              <h3 className="m-0 text-base leading-[1.4] text-(--indigo-dark)">
                {revisionTitle(displayed.revision_no)}
              </h3>
            ) : null}
            <div className="ml-auto inline-flex shrink-0 items-center gap-[3px] rounded-[10px] border border-(--line,#dedee3) bg-white p-[3px]">
              <button
                type="button"
                className="min-h-[27px] cursor-pointer rounded-[7px] border-0 bg-transparent px-[9px] py-1 font-[inherit] text-[0.75rem] font-bold text-(--indigo-dark) transition-[transform,background-color,color] duration-150 hover:enabled:-translate-y-px hover:enabled:bg-(--surface-hover,#ededf0) active:enabled:translate-y-0 active:enabled:bg-(--surface-hover,#ededf0) focus-visible:outline focus-visible:outline-2 focus-visible:outline-(--accent,#76591f) focus-visible:outline-offset-2 disabled:cursor-default disabled:opacity-40"
                onClick={() => void regenerate()}
                disabled={loading || busy || !canRegenerate || reportGenerating}
              >
                {copy.regenerate}
              </button>

              {displayed?.status === "ready" && selectedRevision === null ? (
                <button
                  type="button"
                  className="min-h-[27px] cursor-pointer rounded-[7px] border-0 bg-transparent px-[9px] py-1 font-[inherit] text-[0.75rem] font-bold text-(--indigo-dark) transition-[transform,background-color,color] duration-150 hover:enabled:-translate-y-px hover:enabled:bg-(--surface-hover,#ededf0) active:enabled:translate-y-0 active:enabled:bg-(--surface-hover,#ededf0) focus-visible:outline focus-visible:outline-2 focus-visible:outline-(--accent,#76591f) focus-visible:outline-offset-2 disabled:cursor-default disabled:opacity-40"
                  onClick={() => void download()}
                  disabled={busy}
                >
                  {copy.download}
                </button>
              ) : null}
            </div>
          </div>
          {displayed?.status === "ready" ? (
            <ReportMarkdown
              className="mt-4 max-h-[42rem] overflow-auto whitespace-normal [overflow-wrap:anywhere] font-[inherit] leading-[1.65] text-(--ink)"
              label={copy.report}
            >
              {cleanReportCitations(displayed.english_markdown)}
            </ReportMarkdown>
          ) : displayed?.status === "failed" ? (
            <DismissibleAlert
              className="mt-2 rounded-[0.7rem] bg-[#fff8ec] px-[0.85rem] py-[0.7rem] leading-[1.55] text-[#8b6532]"
              role="status"
            >
              {displayed.safe_error_code}
            </DismissibleAlert>
          ) : report?.generation_status === "failed" ? null : (
            <p className="mt-2 leading-[1.55] text-(--muted)" role="status">
              {copy.generating}
            </p>
          )}
        </div>

        <div className="grid min-w-0 gap-[0.8rem] border-0 border-t border-(--line,#dedee3) bg-transparent p-0 pt-4">
          <div className="flex items-start justify-between gap-4 max-[680px]:flex-wrap max-[680px]:gap-2">
            <h3 className="m-0 text-base leading-[1.4] text-(--muted,#62626a)">
              {copy.history}
            </h3>
          </div>
          {revisions.length === 0 ? (
            <p className="mt-2 leading-[1.55] text-(--muted)">
              {copy.noHistory}
            </p>
          ) : (
            <ul className="m-0 grid list-none gap-2 p-0">
              {revisions.map((revision) => (
                <li
                  key={revision.id}
                  className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 border-b border-[rgba(24,39,61,0.08)] py-[0.55rem] last:border-b-0 max-[680px]:grid-cols-[1fr_auto]"
                >
                  <span>{revisionTitle(revision.revision_no)}</span>
                  <span className="text-[0.8rem] text-[#69778b] max-[680px]:col-start-1">
                    {revision.status !== "ready"
                      ? reportStatusLabel(revision.status)
                      : ""}
                    {revision.word_count
                      ? `${revision.status === "ready" ? "" : " · "}${revision.word_count} ${copy.words}`
                      : ""}
                  </span>
                  <button
                    type="button"
                    className="min-h-[27px] cursor-pointer rounded-[7px] border-0 bg-transparent px-[9px] py-1 font-[inherit] text-[0.75rem] font-bold text-(--indigo-dark) transition-[transform,background-color,color] duration-150 hover:enabled:-translate-y-px hover:enabled:bg-(--surface-hover,#ededf0) active:enabled:translate-y-0 active:enabled:bg-(--surface-hover,#ededf0) focus-visible:outline focus-visible:outline-2 focus-visible:outline-(--accent,#76591f) focus-visible:outline-offset-2 disabled:cursor-default disabled:opacity-40 max-[680px]:col-start-2 max-[680px]:row-span-2 max-[680px]:row-start-1"
                    onClick={() => void selectRevision(revision.id)}
                    disabled={busy}
                    aria-current={
                      selectedRevision?.id === revision.id ? "page" : undefined
                    }
                  >
                    {selectedRevision?.id === revision.id
                      ? copy.selected
                      : copy.view}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}

export default ReportPanel;
