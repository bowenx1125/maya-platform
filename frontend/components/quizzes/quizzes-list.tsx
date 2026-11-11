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
  QuizKey,
  QuizStatus,
  quizState,
} from "./quiz-chrome";
import {
  QuizSticker,
  QuizTakingControls,
  TeacherExtendedSticker,
  TeacherScheduleStickers,
} from "./quiz-taking-controls";

/**
 * Teacher Quizzes (option A, 2026-11-08): one row per quiz with its state
 * chip and counts. The row opens the quiz page. Delete quiz sits on the
 * row, beside that link, and uses the same confirm as the old Paper key.
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
  const [deleteError, setDeleteError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const loadSequence = useRef(0);
  // Set before the request, so a second click cannot send another delete
  // while the first confirm has already been accepted.
  const deletingRef = useRef<string | null>(null);

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

  const onDelete = async (quiz: QuizSummaryDTO) => {
    if (!courseId || deletingRef.current) return;
    if (
      !window.confirm(
        t("quizDeleteConfirm", {
          title: quiz.title.trim() || t("quizEditorNew"),
        }),
      )
    ) {
      return;
    }
    deletingRef.current = quiz.id;
    setDeletingId(quiz.id);
    setDeleteError(null);
    try {
      await quizApi.deleteQuiz(courseId, quiz.id);
      setQuizzes((prev) => prev.filter((row) => row.id !== quiz.id));
    } catch (cause) {
      setDeleteError(cause);
    } finally {
      deletingRef.current = null;
      setDeletingId(null);
    }
  };

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
      {deleteError ? <ErrorNotice error={deleteError} /> : null}
      {actionError ? <ErrorNotice error={actionError} /> : null}
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
                <li key={quiz.id} className={`${QUIZ_ROW} ${LIST_CARD_LIFT}`}>
                  <Link
                    className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3.5 gap-y-2.5 text-ink no-underline max-[600px]:basis-full"
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
                    {state === "draft" ? null : (
                      <>
                        <TeacherScheduleStickers
                          startAt={quiz.scheduled_start_at}
                          endAt={quiz.scheduled_end_at}
                        />
                        <TeacherExtendedSticker count={quiz.exemption_count} />
                      </>
                    )}
                    {quiz.show_results === true ? (
                      <QuizSticker tone="cyan" icon="eye">
                        Results shown
                      </QuizSticker>
                    ) : null}
                    <span aria-hidden="true" className="shrink-0">
                      <WorkspaceIcon name="chevronRight" size={20} stroke={3} />
                    </span>
                  </Link>
                  {state === "draft" ? (
                    <QuizKey
                      icon="trash"
                      busy={deletingId === quiz.id}
                      disabled={deletingId !== null}
                      testId="quiz-delete"
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        void onDelete(quiz);
                      }}
                    >
                      {t("quizDelete")}
                    </QuizKey>
                  ) : (
                    <QuizTakingControls
                      placement="row"
                      courseId={courseId}
                      quiz={quiz}
                      onQuizUpdated={(next) =>
                        setQuizzes((prev) =>
                          prev.map((row) =>
                            row.id === next.id ? { ...row, ...next } : row,
                          ),
                        )
                      }
                      onError={setActionError}
                      trailing={
                        <QuizKey
                          icon="trash"
                          busy={deletingId === quiz.id}
                          disabled={deletingId !== null}
                          testId="quiz-delete"
                          onClick={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            void onDelete(quiz);
                          }}
                        >
                          {t("quizDelete")}
                        </QuizKey>
                      }
                    />
                  )}
                </li>
              );
            })}
          </ul>
        )
      ) : null}
    </div>
  );
}
