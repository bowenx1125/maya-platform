"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { components } from "../../lib/api/generated/schema";
import { apiErrorMessage, type IdempotencyHandle } from "../../lib/api";
import { useIdempotencyStore } from "../../lib/idempotency";
import { useLocale } from "../locale";

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
  return locale === "zh"
    ? `报告修订 ${revision}`
    : `Report revision ${revision}`;
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

  const copy = useMemo(
    () =>
      locale === "zh"
        ? {
            title: "报告",
            insight: "匿名课堂洞察",
            report: "当前报告",
            history: "报告修订历史",
            refresh: "刷新",
            regenerate: "重新生成",
            download: "下载英文 Markdown",
            loading: "正在读取报告状态…",
            noReport: "尚未生成报告。结束课堂互动后，Maya 才会开始生成。",
            noHistory: "还没有报告修订。",
            view: "查看修订",
            selected: "当前查看",
            generating: "Maya 正在整理辩论与匿名课堂洞察。",
            failed: "这次报告生成失败；既有成功修订仍会保留。",
            included: "已纳入",
            filtered: "已筛除",
            words: "词",
          }
        : {
            title: "Report",
            insight: "Anonymous classroom insight",
            report: "Current report",
            history: "Report revision history",
            refresh: "Refresh",
            regenerate: "Regenerate",
            download: "Download English Markdown",
            loading: "Reading report status…",
            noReport:
              "No report has been generated yet. Maya starts after classroom interaction is closed.",
            noHistory: "No report revisions yet.",
            view: "View revision",
            selected: "Viewing",
            generating:
              "Maya is organizing the debate and anonymous classroom insight.",
            failed:
              "This report attempt failed; earlier successful revisions remain available.",
            included: "included",
            filtered: "filtered",
            words: "words",
          },
    [locale],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextReport, nextRevisions] = await Promise.all([
        api.getCurrentReport(debateId),
        api.listReportRevisions(debateId),
      ]);
      setReport(nextReport);
      setRevisions(nextRevisions);
      setSelectedRevision(null);
    } catch (cause) {
      setError(apiErrorMessage(cause));
    } finally {
      setLoading(false);
    }
  }, [api, debateId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

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
      triggerDownload(result.content, result.filename);
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

  if (loading) {
    return (
      <section className={styles.panel} aria-busy="true">
        <p className={styles.loading}>{copy.loading}</p>
      </section>
    );
  }

  const insight = report?.insight;
  const current = report?.current_success_revision ?? null;
  const displayed = selectedRevision ?? current;

  return (
    <section
      className={styles.panel}
      data-report-status={report?.generation_status ?? "not_started"}
      data-insight-status={insight?.status ?? "not_started"}
    >
      <header className={styles.header}>
        <div>
          <h2>{copy.title}</h2>
        </div>
        <div className={styles.actions}>
          <button type="button" onClick={() => void load()} disabled={busy}>
            {copy.refresh}
          </button>
          <button
            type="button"
            onClick={() => void regenerate()}
            disabled={busy || !canRegenerate}
          >
            {copy.regenerate}
          </button>
        </div>
      </header>

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}

      <div className={styles.statusGrid}>
        <div className={styles.statusCard}>
          <span>{copy.insight}</span>
          <strong>
            {reportStatusLabel(locale, insight?.status ?? "not_started")}
          </strong>
          <small>
            {insight?.included_count ?? 0} {copy.included} ·{" "}
            {insight?.filtered_count ?? 0} {copy.filtered}
          </small>
        </div>
        <div className={styles.statusCard}>
          <span>{copy.report}</span>
          <strong>
            {reportStatusLabel(
              locale,
              report?.generation_status ?? "not_started",
            )}
          </strong>
        </div>
      </div>

      {report?.generation_status === "generating" ? (
        <p className={styles.notice} role="status">
          {copy.generating}
        </p>
      ) : null}
      {report?.generation_status === "failed" ? (
        <p className={styles.notice} role="status">
          {copy.failed}
        </p>
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
          <h3>
            {displayed
              ? revisionTitle(locale, displayed.revision_no)
              : copy.report}
          </h3>
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
        {displayed?.status === "ready" ? (
          <pre className={styles.markdown} aria-label={copy.report}>
            {displayed.english_markdown}
          </pre>
        ) : displayed?.status === "failed" ? (
          <p className={styles.notice} role="status">
            {displayed.safe_error_code}
          </p>
        ) : (
          <p className={styles.empty}>{copy.noReport}</p>
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
                  {reportStatusLabel(locale, revision.status)}
                  {revision.word_count
                    ? ` · ${revision.word_count} ${copy.words}`
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
    </section>
  );
}

export default ReportPanel;
