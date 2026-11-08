"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { QuizApi, type QuizSummaryDTO } from "@/lib/api/quiz";
import { useSession } from "../session-provider";
import { useT } from "@/lib/i18n";
import { ErrorNotice, LoadingCard } from "../ui";
import { PageBanner } from "../page-banner";
import { PageAction } from "../page-action";
import { LIST_CARD_LIFT } from "../agent-chrome";
import { WorkspaceIcon } from "../workspace-icon";
import {
  QUIZ_ROW,
  QuizChip,
  QuizEmpty,
  QuizStatus,
  quizState,
} from "./quiz-chrome";

/**
 * Teacher Quizzes (option A, 2026-11-08): one row per quiz with its state
 * chip and counts. Rows carry no keys; a row opens the quiz page, where
 * Start/Pause, Unpublish, Download and grading live.
 */
export function QuizzesList() {
  const t = useT();
  const { api, user } = useSession();
  const quizApi = useMemo(() => new QuizApi(api), [api]);

  const courseId =
    user?.courses.find((m) => m.role === "teacher")?.course_id ?? null;

  const [quizzes, setQuizzes] = useState<QuizSummaryDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const loadSequence = useRef(0);

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    if (!courseId) {
      setQuizzes([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const next = await quizApi.listQuizzes(courseId);
      if (sequence !== loadSequence.current) return;
      setQuizzes(next);
    } catch (cause) {
      if (sequence === loadSequence.current) setError(cause);
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }, [courseId, quizApi]);

  useEffect(() => {
    // Defer past the effect tick like the Debate list: the loader sets
    // state, which must not run synchronously inside the effect body.
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (!courseId) {
    return <QuizEmpty title={t("quizNoCourse")} kind="course" />;
  }

  return (
    <div>
      <PageBanner title={t("quizzes")}>
        <PageAction
          name="new"
          href="/teacher/quizzes/new"
          placement="page"
          className="relative"
        />
      </PageBanner>
      {loading ? <LoadingCard /> : null}
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}
      {!loading && !error ? (
        quizzes.length === 0 ? (
          <QuizEmpty title={t("noQuizzes")} kind="quiz" />
        ) : (
          <ul className="m-0 grid list-none gap-3.5 p-0">
            {quizzes.map((quiz) => {
              const state = quizState(quiz);
              const stateLabel =
                state === "accepting"
                  ? t("quizAccepting")
                  : state === "paused"
                    ? t("quizPaused")
                    : t("quizDraft");
              return (
                <li key={quiz.id}>
                  <Link
                    className={`${QUIZ_ROW} text-ink no-underline ${LIST_CARD_LIFT}`}
                    data-testid="quiz-row"
                    href={`/teacher/quizzes/${quiz.id}`}
                  >
                    <QuizStatus state={state} label={stateLabel} />
                    <span className="min-w-0 flex-[1_1_240px] font-display text-xl leading-tight font-extrabold break-words">
                      {quiz.title}
                    </span>
                    {state === "draft" && !quiz.attempt_count ? null : (
                      <QuizChip>
                        {t("quizAttempts", { count: quiz.attempt_count ?? 0 })}
                      </QuizChip>
                    )}
                    <span aria-hidden="true" className="shrink-0">
                      <WorkspaceIcon name="chevronRight" size={20} stroke={3} />
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )
      ) : null}
    </div>
  );
}
