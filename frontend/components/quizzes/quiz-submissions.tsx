"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { QuizApi } from "@/lib/api/quiz";
import type { RecordAttemptDto } from "@/lib/api/platform";
import { useSession } from "../session-provider";
import { useT } from "@/lib/i18n";
import { ErrorNotice, LoadingCard } from "../ui";
import { QuizAttemptDetailView } from "../quiz/quiz-attempt-detail";
import { QUIZ_ROW_SHELL, QuizEmpty } from "./quiz-chrome";

type Filter = "all" | "to-grade" | number;

/**
 * The Submissions tab of one quiz: its record. One row per student attempt
 * with round, grading state and score; a row opens the marked paper where
 * the teacher grades text answers or hides the attempt.
 */
export function QuizSubmissions({
  courseId,
  quizId,
  onCount,
}: {
  courseId: string;
  quizId: string;
  /** Reports the visible attempt count to the tab label. */
  onCount?: (count: number) => void;
}) {
  const t = useT();
  const { api } = useSession();
  const quizApi = useMemo(() => new QuizApi(api), [api]);

  const [rows, setRows] = useState<RecordAttemptDto[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  const load = useCallback(async () => {
    setError(null);
    try {
      const next = await quizApi.listCourseRecordAttempts(courseId, {
        quizId,
      });
      // The backend may ignore quiz_id; always filter here too.
      const own = next.filter(
        (row) => row.source === "quiz" && row.quiz_id === quizId,
      );
      setRows(own);
      onCount?.(own.length);
    } catch (cause) {
      setError(cause);
    }
  }, [courseId, onCount, quizApi, quizId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (error) {
    return <ErrorNotice inline error={error} onRetry={() => void load()} />;
  }
  if (rows === null) return <LoadingCard />;
  if (rows.length === 0) {
    return <QuizEmpty title={t("quizNoRecords")} kind="records" />;
  }

  const rounds = [
    ...new Set(
      rows
        .map((row) => row.taking_epoch)
        .filter((n): n is number => typeof n === "number"),
    ),
  ].sort((a, b) => a - b);
  const toGrade = rows.filter((row) => row.grading_status !== "complete");
  const shown = rows.filter((row) =>
    filter === "all"
      ? true
      : filter === "to-grade"
        ? row.grading_status !== "complete"
        : row.taking_epoch === filter,
  );

  const filters: Array<{ key: Filter; label: string; warn?: boolean }> = [
    { key: "all", label: t("quizAllRounds") },
    ...(rounds.length > 1
      ? rounds.map((n) => ({ key: n as Filter, label: t("quizRound", { n }) }))
      : []),
    ...(toGrade.length
      ? [
          {
            key: "to-grade" as Filter,
            label: `${t("quizNeedsGrading")} · ${toGrade.length}`,
            warn: true,
          },
        ]
      : []),
  ];

  return (
    <div className="grid gap-4">
      {filters.length > 1 ? (
        <div
          role="group"
          aria-label={t("quizFilterSubmissions")}
          className="flex flex-wrap gap-2"
        >
          {filters.map((item) => {
            const pressed = filter === item.key;
            return (
              <button
                key={String(item.key)}
                type="button"
                aria-pressed={pressed}
                onClick={() => setFilter(item.key)}
                className={`min-h-9 cursor-pointer rounded-full border-2 border-border px-3.5 font-body text-[13px] font-extrabold ${
                  pressed
                    ? "bg-ink text-[#FFE14D]"
                    : item.warn
                      ? "bg-warn-bg text-ink"
                      : "bg-white text-ink"
                }`}
              >
                {item.label}
              </button>
            );
          })}
        </div>
      ) : null}
      <ul className="m-0 grid list-none gap-3 p-0">
        {shown.map((row) => {
          const expanded = openId === row.attempt_id;
          const graded = row.grading_status === "complete";
          const when = row.submitted_at
            ? new Date(row.submitted_at).toLocaleString("en", {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })
            : "";
          const meta = [
            row.taking_epoch ? t("quizRound", { n: row.taking_epoch }) : null,
            when,
          ]
            .filter(Boolean)
            .join(" · ");
          return (
            <li
              key={row.attempt_id}
              // No press motion: its hover hit layer covers the row and would swallow
              // clicks on the grading inputs and buttons inside the opened attempt.
              className={`${QUIZ_ROW_SHELL} overflow-hidden`}
            >
              <button
                type="button"
                className="flex min-w-0 flex-1 cursor-pointer flex-wrap items-center gap-x-3.5 gap-y-1.5 border-0 bg-transparent px-[18px] py-4 text-left font-body text-ink"
                aria-expanded={expanded}
                onClick={() =>
                  setOpenId((current) =>
                    current === row.attempt_id ? null : row.attempt_id,
                  )
                }
              >
                <span className="min-w-0 flex-[1_1_200px] text-[17px] font-extrabold break-words">
                  {row.student_name}
                </span>
                <span className="text-xs font-bold text-arc-muted">{meta}</span>
                <span
                  className={`shrink-0 rounded-full border-2 border-border px-3 py-1 text-xs font-extrabold ${graded ? "bg-[#ECFCCB]" : "bg-warn-bg"}`}
                >
                  {graded ? t("quizGraded") : t("quizNeedsGrading")}
                </span>
                <Score row={row} />
              </button>
              {expanded && row.quiz_id ? (
                <div className="basis-full border-t-[3px] border-dashed border-border p-4">
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
    </div>
  );
}

/** "3 / 6" in mono; totals include hand-graded text questions. */
export function Score({ row }: { row: RecordAttemptDto }) {
  const awarded = row.points_awarded ?? row.score_objective;
  const total = row.points_total ?? row.score_max_objective;
  if (awarded === null || awarded === undefined || !total) return null;
  return (
    <span className="shrink-0 font-mono text-base font-bold whitespace-nowrap">
      {awarded} / {total}
    </span>
  );
}
