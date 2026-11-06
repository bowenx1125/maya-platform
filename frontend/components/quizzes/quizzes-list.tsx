"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { QuizApi, type QuizSummaryDTO } from "@/lib/api/quiz";
import { useSession } from "../session-provider";
import { useT } from "@/lib/i18n";
import { Button } from "../ui/button";
import { EmptyCard, ErrorNotice, LoadingCard } from "../ui";
import { PageBanner } from "../page-banner";
import { PageAction } from "../page-action";
import { LIST_CARD_LIFT } from "../agent-chrome";

export function QuizzesList() {
  const t = useT();
  const { api, user } = useSession();
  const quizApi = useMemo(() => new QuizApi(api), [api]);

  const courseId =
    user?.courses.find((m) => m.role === "teacher")?.course_id ?? null;

  const [quizzes, setQuizzes] = useState<QuizSummaryDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [unpublishingId, setUnpublishingId] = useState<string | null>(null);
  const [evalBusyId, setEvalBusyId] = useState<string | null>(null);
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

  const unpublish = async (quizId: string) => {
    if (!courseId) return;
    setUnpublishingId(quizId);
    setError(null);
    try {
      await quizApi.unpublishQuiz(courseId, quizId);
      await load();
    } catch (cause) {
      setError(cause);
    } finally {
      setUnpublishingId(null);
    }
  };

  const toggleEvaluation = async (
    quiz: QuizSummaryDTO,
    next: "start" | "pause",
  ) => {
    if (!courseId) return;
    setEvalBusyId(quiz.id);
    setError(null);
    try {
      if (next === "start") {
        await quizApi.startTaking(courseId, quiz.id);
      } else {
        await quizApi.pauseTaking(courseId, quiz.id);
      }
      await load();
    } catch (cause) {
      setError(cause);
    } finally {
      setEvalBusyId(null);
    }
  };

  if (!courseId) {
    return <EmptyCard title={t("quizzes")}>{t("quizNoCourse")}</EmptyCard>;
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
          <EmptyCard title={t("noQuizzes")} />
        ) : (
          <div className="grid gap-3.5">
            {quizzes.map((quiz) => {
              const takingOpen = quiz.taking_open === true;
              const evalBusy = evalBusyId === quiz.id;
              return (
                <article
                  className={`relative rounded-[18px] border-2 border-[#111] bg-white p-4 shadow-[0_4px_0_#111] ${LIST_CARD_LIFT}`}
                  data-testid="quiz-row"
                  key={quiz.id}
                >
                  <Link
                    aria-label={quiz.title}
                    className="absolute inset-0 z-0 rounded-[18px]"
                    href={`/teacher/quizzes/${quiz.id}`}
                  />
                  <div className="relative z-10 flex items-start justify-between gap-3 pointer-events-none">
                    <div className="min-w-0 flex-1">
                      <div className="font-display text-lg font-bold text-inherit">
                        {quiz.title}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2 font-body text-xs font-bold [&>span]:rounded-full [&>span]:border-2 [&>span]:border-[#111] [&>span]:bg-white [&>span]:px-2.5 [&>span]:py-px">
                        <span>
                          {quiz.status === "published"
                            ? t("quizPublished")
                            : t("quizDraft")}
                        </span>
                        {quiz.status === "published" ? (
                          <span>
                            {takingOpen ? t("quizAccepting") : t("quizPaused")}
                          </span>
                        ) : null}
                        <span>
                          {new Date(quiz.updated_at).toLocaleDateString()}
                        </span>
                        <span>
                          {t("quizAttempts", {
                            count: quiz.attempt_count ?? 0,
                          })}
                        </span>
                      </div>
                    </div>
                    <div className="pointer-events-auto flex shrink-0 flex-wrap items-center justify-end gap-2">
                      <Link
                        className="relative inline-flex h-10 items-center rounded-[var(--radius-base)] border-[3px] border-[var(--border)] bg-white px-3 font-body text-sm font-bold text-ink no-underline shadow-[0_6px_0_#111] transition-[translate,box-shadow] duration-150 ease-[cubic-bezier(.2,.8,.2,1)] hover:-translate-y-0.5 active:translate-y-1.5 active:shadow-none"
                        href={`/teacher/quizzes/records?quiz_id=${encodeURIComponent(quiz.id)}`}
                        onClick={(event) => event.stopPropagation()}
                      >
                        {t("quizViewRecords")}
                      </Link>
                      {quiz.status === "published" ? (
                        <>
                          {takingOpen ? (
                            <Button
                              className="relative"
                              type="button"
                              variant="neutral"
                              disabled={evalBusy}
                              busy={evalBusy}
                              onClick={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                void toggleEvaluation(quiz, "pause");
                              }}
                            >
                              {t("quizPauseEvaluation")}
                            </Button>
                          ) : (
                            <Button
                              className="relative"
                              type="button"
                              disabled={evalBusy}
                              busy={evalBusy}
                              onClick={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                void toggleEvaluation(quiz, "start");
                              }}
                            >
                              {t("quizStartEvaluation")}
                            </Button>
                          )}
                          <Button
                            className="relative"
                            variant="noShadow"
                            type="button"
                            disabled={unpublishingId === quiz.id}
                            onClick={(event) => {
                              event.preventDefault();
                              event.stopPropagation();
                              void unpublish(quiz.id);
                            }}
                          >
                            {t("quizUnpublish")}
                          </Button>
                        </>
                      ) : null}
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )
      ) : null}
    </div>
  );
}
