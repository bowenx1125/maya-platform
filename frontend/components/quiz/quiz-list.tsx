"use client";

import { useCallback, useEffect, useState } from "react";

import {
  apiErrorMessage,
  type PlatformApi,
  type QuizSummary,
  type RecordAttemptDto,
} from "../../lib/api";
import { canStudentStartQuiz } from "../../lib/quiz-gate";
import { cachedCall, requestCacheIdentity } from "../../lib/request-cache";
import { useT } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { useSession } from "../session-provider";
import { ErrorNotice, LoadingCard } from "../ui";
import { IconLock } from "../quiet-icons";
import {
  QUIZ_ROW,
  QUIZ_ROW_SHELL,
  QuizEmpty,
  QuizKey,
} from "../quizzes/quiz-chrome";
import { Score } from "../quizzes/quiz-submissions";
import { QuizAttemptDetailView } from "./quiz-attempt-detail";

type ListApi = Pick<PlatformApi, "listCourseQuizzes" | "listMyRecordAttempts">;

const WHEN: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };

/**
 * The student's one Quiz list (option A, 2026-11-08): quizzes open now with
 * Start, then their own results (a row opens the marked paper, no key), then
 * quizzes not open yet. Results replace the old Records tab.
 */
export function StudentQuizList({
  courseId,
  onStart,
  fresh = false,
  api: apiProp,
}: {
  courseId: string;
  onStart: (quiz: QuizSummary) => void;
  /** Skip the request cache on the first load (back from taking a quiz). */
  fresh?: boolean;
  /** Test seam; production resolves useSession().api. */
  api?: ListApi;
}) {
  const t = useT();
  const session = useSession();
  const client = apiProp ?? (session.api as ListApi);
  const cacheIdentity = requestCacheIdentity(
    session.user?.id,
    session.identityGeneration,
  );
  const [quizzes, setQuizzes] = useState<QuizSummary[] | null>(null);
  const [results, setResults] = useState<RecordAttemptDto[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(
    async (refresh = false) => {
      setError(null);
      try {
        const [nextQuizzes, nextResults] = await Promise.all([
          cachedCall(
            client,
            cacheIdentity,
            "listCourseQuizzes",
            [courseId],
            () => client.listCourseQuizzes(courseId),
            { refresh },
          ),
          cachedCall(
            client,
            cacheIdentity,
            "listMyRecordAttempts",
            [courseId],
            () => client.listMyRecordAttempts(courseId),
            { refresh },
          ),
        ]);
        // The server lists published only for a student; filter anyway so a
        // stale cached draft row can never start a draft quiz.
        setQuizzes(nextQuizzes.filter((quiz) => quiz.status === "published"));
        setResults(
          nextResults
            .filter((row) => row.source === "quiz")
            .sort((a, b) =>
              (b.submitted_at ?? "").localeCompare(a.submitted_at ?? ""),
            ),
        );
      } catch (cause) {
        setError(cause);
      }
    },
    [cacheIdentity, client, courseId],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => void load(fresh), 0);
    return () => window.clearTimeout(timer);
  }, [fresh, load]);

  if (error) {
    return <ErrorNotice inline error={error} onRetry={() => void load(true)} />;
  }
  if (quizzes === null || results === null) return <LoadingCard />;

  const takenThisRound = (quiz: QuizSummary) =>
    results.some(
      (row) =>
        row.quiz_id === quiz.id &&
        quiz.taking_epoch !== undefined &&
        row.taking_epoch === quiz.taking_epoch,
    );
  const toTake = quizzes.filter(
    (quiz) => canStudentStartQuiz(quiz) && !takenThisRound(quiz),
  );
  const notOpen = quizzes.filter(
    (quiz) =>
      !canStudentStartQuiz(quiz) &&
      !results.some((row) => row.quiz_id === quiz.id),
  );

  if (!toTake.length && !results.length && !notOpen.length) {
    return <QuizEmpty title="No quizzes yet." kind="quiz" />;
  }

  return (
    <ul aria-label="Quizzes" className="m-0 grid list-none gap-3 p-0">
      {toTake.map((quiz) => (
        <li
          key={`take-${quiz.id}`}
          className={cn(QUIZ_ROW, "shadow-[4px_4px_0_#A3E635]")}
        >
          <span className="min-w-0 flex-[1_1_240px] font-display text-xl leading-tight font-extrabold break-words">
            {quiz.title}
          </span>
          <QuizKey icon="play" tone="primary" onClick={() => onStart(quiz)}>
            Start
          </QuizKey>
        </li>
      ))}
      {results.map((row) => {
        const expanded = openId === row.attempt_id;
        const graded = row.grading_status === "complete";
        const meta = [
          row.taking_epoch ? t("quizRound", { n: row.taking_epoch }) : null,
          row.submitted_at
            ? new Date(row.submitted_at).toLocaleDateString("en", WHEN)
            : null,
        ]
          .filter(Boolean)
          .join(" · ");
        return (
          <li
            key={row.attempt_id}
            // No press motion: a hover hit layer would cover the opened paper.
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
              <span className="min-w-0 flex-[1_1_240px] font-display text-xl leading-tight font-extrabold break-words">
                {row.title}
              </span>
              <span className="text-xs font-bold text-arc-muted">{meta}</span>
              <span
                className={`shrink-0 rounded-full border-2 border-border px-3 py-1 text-xs font-extrabold ${graded ? "bg-[#ECFCCB]" : "bg-warn-bg"}`}
              >
                {graded ? t("quizGraded") : t("quizNotGraded")}
              </span>
              <Score row={row} />
            </button>
            {expanded && row.quiz_id ? (
              <div className="basis-full border-t-[3px] border-dashed border-border p-4">
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
      {notOpen.map((quiz) => (
        <li key={`closed-${quiz.id}`} className={QUIZ_ROW}>
          <span className="min-w-0 flex-[1_1_240px] font-display text-xl leading-tight font-extrabold break-words">
            {quiz.title}
          </span>
          <span
            className="inline-flex items-center gap-1.5 rounded-full border-2 border-border bg-white px-3 py-1 font-body text-xs font-extrabold text-arc-muted"
            data-testid="quiz-not-open"
          >
            <IconLock size={14} />
            {t("quizNotOpenYet")}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function quizLoadMessage(error: unknown): string {
  return apiErrorMessage(error, "Could not load the quiz.");
}
