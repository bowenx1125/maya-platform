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
import {
  LiveLamp,
  QuizChip,
  QuizEmpty,
  QuizKey,
  QuizStatus,
  STATE_SHADOW,
  quizState,
} from "./quiz-chrome";

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
          <div className="grid gap-5">
            {quizzes.map((quiz) => {
              const state = quizState(quiz);
              const published = quiz.status === "published";
              const evalBusy = evalBusyId === quiz.id;
              const stateLabel =
                state === "accepting"
                  ? t("quizAccepting")
                  : state === "paused"
                    ? `${t("quizPublished")} · ${t("quizPaused")}`
                    : t("quizDraft");
              return (
                <article
                  className={`relative flex flex-wrap items-center gap-4 rounded-[18px] border-[3px] border-[#111] bg-white px-[22px] py-5 ${STATE_SHADOW[state]} ${LIST_CARD_LIFT}`}
                  data-testid="quiz-row"
                  key={quiz.id}
                >
                  <Link
                    aria-label={quiz.title}
                    className="absolute inset-0 z-0 rounded-[18px]"
                    href={`/teacher/quizzes/${quiz.id}`}
                  />
                  <div className="pointer-events-none relative z-10 flex min-w-0 flex-[999_1_320px] flex-col gap-2.5">
                    <h2 className="m-0 font-display text-2xl leading-tight font-extrabold text-[#111]">
                      {quiz.title}
                    </h2>
                    <div className="flex flex-wrap items-center gap-2">
                      <QuizStatus state={state} label={stateLabel} />
                      {state === "accepting" ? <LiveLamp /> : null}
                      <QuizChip>
                        {new Date(quiz.updated_at).toLocaleDateString("en", {
                          month: "short",
                          day: "numeric",
                        })}
                      </QuizChip>
                      <QuizChip>
                        {t("quizAttempts", { count: quiz.attempt_count ?? 0 })}
                      </QuizChip>
                    </div>
                  </div>
                  <div className="relative z-10 flex flex-[1_1_auto] flex-wrap justify-end gap-2.5">
                    <QuizKey
                      icon="clock"
                      href={`/teacher/quizzes/records?quiz_id=${encodeURIComponent(quiz.id)}`}
                      onClick={(event) => event.stopPropagation()}
                    >
                      {t("quizViewRecords")}
                    </QuizKey>
                    {published ? (
                      <>
                        {state === "accepting" ? (
                          <QuizKey
                            icon="pause"
                            busy={evalBusy}
                            onClick={(event) => {
                              event.preventDefault();
                              event.stopPropagation();
                              void toggleEvaluation(quiz, "pause");
                            }}
                          >
                            {t("quizPauseEvaluation")}
                          </QuizKey>
                        ) : (
                          <QuizKey
                            icon="play"
                            tone="primary"
                            busy={evalBusy}
                            onClick={(event) => {
                              event.preventDefault();
                              event.stopPropagation();
                              void toggleEvaluation(quiz, "start");
                            }}
                          >
                            {t("quizStartEvaluation")}
                          </QuizKey>
                        )}
                        <QuizKey
                          icon="undo"
                          busy={unpublishingId === quiz.id}
                          onClick={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            void unpublish(quiz.id);
                          }}
                        >
                          {t("quizUnpublish")}
                        </QuizKey>
                      </>
                    ) : null}
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
