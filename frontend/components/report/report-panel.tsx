"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DismissibleAlert } from "../dismissible-alert";
import type { components } from "../../lib/api/generated/schema";
import { apiErrorMessage, type IdempotencyHandle } from "../../lib/api";
import { useIdempotencyStore } from "../../lib/idempotency";
import { nextPollDelay } from "../../lib/poll-pacing";
import { useLocale } from "../locale";
import {
  cleanReportCitations,
  reportLengthUnit,
} from "../../lib/report-citations";
import { ReportMarkdown } from "./report-markdown";

import styles from "./report.module.css";

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

function reportStatusLabel(locale: "en" | "zh", status: string): string {
  const labels: Record<string, [string, string]> = {
    not_started: ["Not started", "尚未生成"],
    generating: ["Generating", "生成中"],
    ready: ["Ready", "已就绪"],
    failed: ["Failed", "失败"],
  };
  return labels[status]?.[locale === "zh" ? 1 : 0] ?? status;
}

function revisionTitle(locale: "en" | "zh", revision: number): string {
  return locale === "zh" ? `版本 ${revision}` : `Version ${revision}`;
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
  const { locale } = useLocale();
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

  const copy = useMemo(
    () =>
      locale === "zh"
        ? {
            title: "报告",
            insight: "匿名课堂洞察",
            report: "当前报告",
            history: "历史",
            regenerate: "重新生成",
            download: "下载",
            noHistory: "还没有报告版本。",
            view: "查看",
            selected: "当前查看",
            generating: "报告生成中…",
            failed: "报告生成失败；既有成功修订仍会保留。",
            included: "已纳入",
            filtered: "已筛除",
            words: reportLengthUnit("zh"),
          }
        : {
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
          },
    [locale],
  );

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
      className={styles.panel}
      aria-busy={loading || polling}
      data-report-status={report?.generation_status ?? "not_started"}
      data-insight-status={insight?.status ?? "not_started"}
    >
      <header className={styles.header}>
        <div>
          <h2>{copy.title}</h2>
        </div>
      </header>

      <div className={styles.content}>
        {error ? (
          <DismissibleAlert className={styles.error}>{error}</DismissibleAlert>
        ) : null}

        {pollTimedOut && polling ? (
          <p className={styles.notice} role="status">
            {locale === "zh"
              ? "报告仍在生成，请稍后重新打开。"
              : "The report is still generating. Reopen this page later."}
          </p>
        ) : null}
        {report?.generation_status === "failed" ||
        insight?.status === "failed" ? (
          <DismissibleAlert className={styles.notice} role="status">
            {copy.failed}
          </DismissibleAlert>
        ) : null}

        {insight?.items.length ? (
          <ul className={styles.insightList} aria-label={copy.insight}>
            {insight.items.map((item, index) => (
              <li key={`${item.category}-${item.summary}-${index}`}>
                <span>{item.category}</span>
                <p>{item.summary}</p>
                <strong>{item.count}</strong>
              </li>
            ))}
          </ul>
        ) : null}

        <div className={styles.reportCard}>
          <div className={styles.cardHeading}>
            {displayed ? (
              <h3>{revisionTitle(locale, displayed.revision_no)}</h3>
            ) : null}
            <div className={styles.actions}>
              <button
                type="button"
                onClick={() => void regenerate()}
                disabled={loading || busy || !canRegenerate || reportGenerating}
              >
                {copy.regenerate}
              </button>

              {displayed?.status === "ready" && selectedRevision === null ? (
                <button
                  type="button"
                  onClick={() => void download()}
                  disabled={busy}
                >
                  {copy.download}
                </button>
              ) : null}
            </div>
          </div>
          {displayed?.status === "ready" ? (
            <ReportMarkdown className={styles.markdown} label={copy.report}>
              {cleanReportCitations(displayed.english_markdown)}
            </ReportMarkdown>
          ) : displayed?.status === "failed" ? (
            <DismissibleAlert className={styles.notice} role="status">
              {displayed.safe_error_code}
            </DismissibleAlert>
          ) : report?.generation_status === "failed" ? null : (
            <p className={styles.empty} role="status">
              {copy.generating}
            </p>
          )}
        </div>

        <div className={styles.history}>
          <div className={styles.cardHeading}>
            <h3>{copy.history}</h3>
          </div>
          {revisions.length === 0 ? (
            <p className={styles.empty}>{copy.noHistory}</p>
          ) : (
            <ul>
              {revisions.map((revision) => (
                <li key={revision.id}>
                  <span>{revisionTitle(locale, revision.revision_no)}</span>
                  <span className={styles.revisionStatus}>
                    {revision.status !== "ready"
                      ? reportStatusLabel(locale, revision.status)
                      : ""}
                    {revision.word_count
                      ? `${revision.status === "ready" ? "" : " · "}${revision.word_count} ${copy.words}`
                      : ""}
                  </span>
                  <button
                    type="button"
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
