"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";

import {
  apiErrorMessage,
  type PlatformApi,
  type RecordAttemptDto,
} from "../../lib/api";
import { cachedCall, requestCacheIdentity } from "../../lib/request-cache";
import { useSession } from "../session-provider";
import { ErrorNotice, LoadingCard } from "../ui";
import { useT } from "../../lib/i18n";
import { AssessmentRecordPanel } from "../knowledge/assessment-record";
import { QuizAttemptDetailView } from "./quiz-attempt-detail";

type RecordsApi = Pick<PlatformApi, "listMyRecordAttempts">;

/**
 * The student's own quiz submissions with their answers and grades, then the
 * formal chat-assessment Record (moved here from Brainform, 2026-11-08).
 */
export function QuizRecords({
  courseId,
  api: apiProp,
}: {
  courseId: string;
  /** Test seam; production resolves useSession().api. */
  api?: RecordsApi;
}) {
  const t = useT();
  const session = useSession();
  const client = apiProp ?? (session.api as RecordsApi);
  const cacheIdentity = requestCacheIdentity(
    session.user?.id,
    session.identityGeneration,
  );
  const [rows, setRows] = useState<RecordAttemptDto[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(
    async (refresh = false) => {
      setError(null);
      try {
        const next = await cachedCall(
          client,
          cacheIdentity,
          "listMyRecordAttempts",
          [courseId],
          () => client.listMyRecordAttempts(courseId),
          { refresh },
        );
        // Chat rows are read by the Record board below with their answers.
        setRows(next.filter((row) => row.source === "quiz"));
      } catch (cause) {
        setError(cause);
      }
    },
    [cacheIdentity, client, courseId],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return (
    <div className="grid gap-8">
      {error ? (
        <ErrorNotice inline error={error} onRetry={() => void load(true)} />
      ) : rows === null ? (
        <LoadingCard />
      ) : !rows.length ? (
        <p className="m-0 rounded-arc-s border-[3px] border-border bg-surface px-4 py-6 text-center font-body text-sm font-bold text-ink shadow-[4px_4px_0_#111]">
          {t("quizNoSubmissions")}
        </p>
      ) : (
        <RecordList
          rows={rows}
          courseId={courseId}
          openId={openId}
          setOpenId={setOpenId}
        />
      )}
      <AssessmentRecordPanel courseId={courseId} scope="own" />
    </div>
  );
}

function RecordList({
  rows,
  courseId,
  openId,
  setOpenId,
}: {
  rows: RecordAttemptDto[];
  courseId: string;
  openId: string | null;
  setOpenId: (update: (current: string | null) => string | null) => void;
}) {
  const t = useT();
  return (
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
              className="flex min-w-0 flex-1 cursor-pointer items-center gap-3.5 border-0 bg-transparent p-0 text-left font-body text-inherit"
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
                  {row.taking_epoch
                    ? `${t("quizRound", { n: row.taking_epoch })} · `
                    : ""}
                  {row.submitted_at
                    ? new Date(row.submitted_at).toLocaleString("en", {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })
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
                  teacher={false}
                />
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function recordRatio(row: RecordAttemptDto): number | null {
  // Totals include hand-graded text questions; objective-only is a fallback.
  const awarded = row.points_awarded ?? row.score_objective;
  const total = row.points_total ?? row.score_max_objective;
  if (awarded === null || awarded === undefined || !total) return null;
  return Math.max(0, Math.min(1, awarded / total));
}

/** Copied minimal version of assessment-record's ScoreRing (not exported there). */
export function ScoreRing({ ratio }: { ratio: number | null }) {
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

export function recordErrorMessage(error: unknown): string {
  return apiErrorMessage(error, "Could not load records.");
}
