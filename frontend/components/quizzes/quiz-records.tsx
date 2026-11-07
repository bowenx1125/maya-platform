"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
} from "react";
import { useSearchParams } from "next/navigation";

import { QuizApi } from "@/lib/api/quiz";
import type { RecordAttemptDto } from "@/lib/api/platform";
import { shouldShowExportDownload } from "@/lib/quiz-urls";
import { useSession } from "../session-provider";
import { useT } from "@/lib/i18n";
import { PageBanner } from "../page-banner";
import { PageAction } from "../page-action";
import { EmptyCard, ErrorNotice, LoadingCard } from "../ui";
import { BUSY_MOTION, PRESS_MOTION } from "../ui/button";
import { IconDownload } from "../quiet-icons";
import { cn } from "../../lib/utils";
import { AssessmentRecordPanel } from "../knowledge/assessment-record";
import { QuizAttemptDetailView } from "../quiz/quiz-attempt-detail";

function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noreferrer";
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Match PageAction banner chrome (WorkspaceActionName has no download yet). */
const BANNER_DOWNLOAD = `inline-flex h-auto min-h-11 w-auto shrink-0 cursor-pointer items-center gap-1.5 rounded-[10px] border-[3px] border-[#111] bg-white px-4 py-[7px] font-body text-sm [line-height:normal] font-extrabold text-[#111] no-underline disabled:cursor-not-allowed disabled:opacity-50 disabled:aria-busy:opacity-100 [&_svg]:size-4 ${PRESS_MOTION} ${BUSY_MOTION}`;

export default function QuizRecords() {
  const t = useT();
  const { api, user } = useSession();
  const searchParams = useSearchParams();
  const quizIdFilter = searchParams.get("quiz_id") ?? undefined;
  const quizApi = useMemo(() => new QuizApi(api), [api]);

  const courseId =
    user?.courses.find((m) => m.role === "teacher")?.course_id ?? null;

  const [rows, setRows] = useState<RecordAttemptDto[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState<unknown>(null);

  const load = useCallback(async () => {
    if (!courseId) {
      setRows([]);
      return;
    }
    setError(null);
    try {
      const next = await quizApi.listCourseRecordAttempts(courseId, {
        quizId: quizIdFilter,
      });
      // Backend may ignore quiz_id; always filter client-side when set.
      // Chat-assessment rows render in the Record board below, with their
      // answer sheets, so this list keeps quiz submissions only.
      const filtered = next.filter(
        (row) =>
          row.source === "quiz" &&
          (!quizIdFilter || row.quiz_id === quizIdFilter),
      );
      setRows(filtered);
    } catch (cause) {
      setError(cause);
    }
  }, [courseId, quizApi, quizIdFilter]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const onExport = useCallback(async () => {
    if (!courseId || !quizIdFilter) return;
    setExportBusy(true);
    setExportError(null);
    try {
      const result = await quizApi.exportAttempts(courseId, quizIdFilter);
      triggerBlobDownload(result.blob, result.filename);
    } catch (cause) {
      setExportError(cause);
    } finally {
      setExportBusy(false);
    }
  }, [courseId, quizApi, quizIdFilter]);

  if (!courseId) {
    return <EmptyCard title={t("quizRecords")}>{t("quizNoCourse")}</EmptyCard>;
  }

  const showDownload = shouldShowExportDownload(quizIdFilter);

  return (
    <div>
      <PageBanner title={t("quizRecords")}>
        <PageAction
          name="back"
          href="/teacher/quizzes"
          placement="page"
          className="relative"
        />
        {showDownload ? (
          <button
            type="button"
            className={cn(BANNER_DOWNLOAD, "relative")}
            disabled={exportBusy}
            aria-busy={exportBusy || undefined}
            onClick={() => void onExport()}
            data-testid="quiz-export-download"
            data-ui-guide="quiz.exportDownload"
          >
            {exportBusy ? (
              <span className="spinner" aria-hidden="true" />
            ) : (
              <IconDownload size={16} />
            )}
            <span>{t("download")}</span>
          </button>
        ) : null}
      </PageBanner>
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}
      {exportError ? (
        <ErrorNotice error={exportError} onRetry={() => void onExport()} />
      ) : null}
      {rows === null && !error ? <LoadingCard /> : null}
      {rows && rows.length === 0 && !error ? (
        <EmptyCard
          title={quizIdFilter ? t("quizNoRecords") : t("quizNoSubmissions")}
        />
      ) : null}
      {rows && rows.length > 0 ? (
        <ul className="m-0 grid list-none gap-4 p-0">
          {rows.map((row, index) => {
            const expanded = openId === row.attempt_id;
            return (
              <li
                key={row.attempt_id}
                // No press motion: its hover hit layer covers the row and would swallow
                // clicks on the grading inputs and buttons inside the opened attempt.
                className="relative flex flex-wrap items-center gap-3.5 rounded-[14px] border-[3px] border-border bg-white px-[18px] py-4 shadow-[6px_6px_0_#67E8F9]"
              >
                <span
                  aria-hidden="true"
                  className="w-7 shrink-0 font-mono text-sm font-extrabold text-[#9CA3AF]"
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <button
                  type="button"
                  className="relative flex min-w-0 flex-1 cursor-pointer items-center gap-3.5 border-0 bg-transparent p-0 text-left font-body text-inherit"
                  aria-expanded={expanded}
                  onClick={() =>
                    setOpenId((current) =>
                      current === row.attempt_id ? null : row.attempt_id,
                    )
                  }
                >
                  <span className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="text-[17px] font-extrabold text-ink">
                      {row.title}
                    </span>
                    <span className="text-xs font-medium text-[#555]">
                      {row.student_name}
                      {row.taking_epoch
                        ? ` · ${t("quizRound", { n: row.taking_epoch })}`
                        : ""}
                      {row.submitted_at
                        ? ` · ${new Date(row.submitted_at).toLocaleString(
                            "en",
                            {
                              month: "short",
                              day: "numeric",
                              hour: "2-digit",
                              minute: "2-digit",
                            },
                          )}`
                        : ""}
                    </span>
                  </span>
                  <span
                    className={`shrink-0 rounded-full border-2 border-border px-3 py-1 font-body text-[10px] leading-none font-extrabold tracking-[0.08em] uppercase ${
                      row.source === "quiz"
                        ? "bg-main text-main-fg"
                        : "bg-surface text-ink"
                    }`}
                  >
                    {row.source}
                  </span>
                  <ScoreRing ratio={recordRatio(row)} />
                </button>
                {expanded && row.quiz_id ? (
                  <div className="basis-full pt-3">
                    <QuizAttemptDetailView
                      courseId={courseId}
                      quizId={row.quiz_id}
                      attemptId={row.attempt_id}
                      teacher
                      onChanged={() => void load()}
                      onHidden={() => {
                        setOpenId(null);
                        void load();
                      }}
                    />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      {quizIdFilter ? null : (
        <div className="mt-8">
          <AssessmentRecordPanel courseId={courseId} scope="course" />
        </div>
      )}
    </div>
  );
}

function recordRatio(row: RecordAttemptDto): number | null {
  // Totals include hand-graded text questions; objective-only is a fallback.
  const awarded = row.points_awarded ?? row.score_objective;
  const total = row.points_total ?? row.score_max_objective;
  if (awarded === null || awarded === undefined || !total) return null;
  return Math.max(0, Math.min(1, awarded / total));
}

function ScoreRing({ ratio }: { ratio: number | null }) {
  if (ratio === null) return null;
  const percent = Math.round(ratio * 100);
  return (
    <span
      className="grid h-12 w-12 shrink-0 place-items-center rounded-full border-[3px] border-border shadow-[3px_3px_0_#FF4D8D]"
      style={
        {
          background: `conic-gradient(#FF4D8D ${percent}%, #fff 0)`,
        } as CSSProperties
      }
      aria-hidden="true"
    >
      <span className="grid h-8 w-8 place-items-center rounded-full border-2 border-border bg-white font-mono text-xs font-extrabold text-ink">
        {percent}
      </span>
    </span>
  );
}
