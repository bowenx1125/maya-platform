"use client";

import { useCallback, useEffect, useState } from "react";

import { apiErrorMessage, type QuizSummary } from "../../lib/api";
import { cachedCall, requestCacheIdentity } from "../../lib/request-cache";
import { useSession } from "../session-provider";
import { ErrorNotice, LoadingCard } from "../ui";

/**
 * Available: the course's published quizzes. Start opens the take view; the
 * server returns published only for a student, but the list still filters,
 * so a stale cached draft row can never start a draft quiz.
 */
export function QuizAvailable({
  courseId,
  onStart,
}: {
  courseId: string;
  onStart: (quiz: QuizSummary) => void;
}) {
  const { api, identityGeneration, user } = useSession();
  const cacheIdentity = requestCacheIdentity(user?.id, identityGeneration);
  const [quizzes, setQuizzes] = useState<QuizSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(
    async (refresh = false) => {
      setError(null);
      try {
        const next = await cachedCall(
          api,
          cacheIdentity,
          "listCourseQuizzes",
          [courseId],
          () => api.listCourseQuizzes(courseId),
          { refresh },
        );
        setQuizzes(next.filter((quiz) => quiz.status === "published"));
      } catch (cause) {
        setError(cause);
      }
    },
    [api, cacheIdentity, courseId],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (error) {
    return (
      <ErrorNotice
        inline
        error={error}
        onRetry={() => void load(true)}
      />
    );
  }
  if (quizzes === null) return <LoadingCard />;
  if (!quizzes.length) {
    return (
      <p className="m-0 rounded-arc-s border-[3px] border-border bg-surface px-4 py-6 text-center font-body text-sm font-bold text-ink shadow-[4px_4px_0_#111]">
        No quizzes yet.
      </p>
    );
  }
  return (
    <ul className="m-0 grid list-none gap-4 p-0">
      {quizzes.map((quiz, index) => (
        <li
          key={quiz.id}
          className="relative flex flex-wrap items-center gap-3.5 rounded-[14px] border-[3px] border-border bg-white px-[18px] py-4 shadow-[6px_6px_0_#C4B5FD]"
        >
          <span
            aria-hidden="true"
            className="w-7 shrink-0 font-mono text-sm font-extrabold text-[#9CA3AF]"
          >
            {String(index + 1).padStart(2, "0")}
          </span>
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="font-body text-[17px] font-extrabold text-ink">
              {quiz.title}
            </span>
            <span className="font-body text-xs font-medium text-[#555]">
              {quiz.published_at
                ? new Date(quiz.published_at).toLocaleString("en", {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : ""}
          </span>
          </span>
          <button
            type="button"
            onClick={() => onStart(quiz)}
            className="inline-flex min-h-10 cursor-pointer items-center rounded-[10px] border-[3px] border-border bg-main px-[18px] py-2 font-body text-sm font-bold text-main-fg no-underline shadow-[0_6px_0_#111] transition-[translate,box-shadow] duration-150 ease-[cubic-bezier(.2,.8,.2,1)] hover:-translate-y-0.5 active:translate-y-1.5 active:shadow-none active:duration-[80ms] motion-reduce:transition-colors motion-reduce:hover:translate-y-0 motion-reduce:active:translate-y-0"
          >
            Start
          </button>
        </li>
      ))}
    </ul>
  );
}

export function quizLoadMessage(error: unknown): string {
  return apiErrorMessage(error, "Could not load the quiz.");
}
