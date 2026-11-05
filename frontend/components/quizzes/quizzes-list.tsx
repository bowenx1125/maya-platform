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

  if (!courseId) {
    return <EmptyCard title={t("quizzes")}>{t("quizNoCourse")}</EmptyCard>;
  }

  return (
    <div>
      <PageBanner title={t("quizzes")}>
        <PageAction name="new" href="/teacher/quizzes/new" placement="page" />
      </PageBanner>
      {loading ? <LoadingCard /> : null}
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}
      {!loading && !error ? (
        quizzes.length === 0 ? (
          <EmptyCard>{t("noQuizzes")}</EmptyCard>
        ) : (
          <div className="grid gap-3.5">
            {quizzes.map((quiz) => (
              <div
                className={`rounded-[18px] border-2 border-[#111] bg-white p-4 shadow-[0_4px_0_#111] ${LIST_CARD_LIFT}`}
                data-testid="quiz-row"
                key={quiz.id}
              >
                <div className="flex items-start justify-between gap-3">
                  <Link
                    className="font-display text-lg font-bold text-inherit no-underline hover:underline"
                    href={`/teacher/quizzes/${quiz.id}`}
                  >
                    {quiz.title}
                  </Link>
                  {quiz.status === "published" ? (
                    <Button
                      variant="noShadow"
                      type="button"
                      disabled={unpublishingId === quiz.id}
                      onClick={() => void unpublish(quiz.id)}
                    >
                      {t("quizUnpublish")}
                    </Button>
                  ) : null}
                </div>
                <div className="mt-2 flex flex-wrap gap-2 font-body text-xs font-bold [&>span]:rounded-full [&>span]:border-2 [&>span]:border-[#111] [&>span]:bg-white [&>span]:px-2.5 [&>span]:py-px">
                  <span>
                    {quiz.status === "published"
                      ? t("quizPublished")
                      : t("quizDraft")}
                  </span>
                  <span>{new Date(quiz.updated_at).toLocaleDateString()}</span>
                  {quiz.attempt_count && quiz.attempt_count > 0 ? (
                    <span>
                      {t("quizAttempts", { count: quiz.attempt_count })}
                    </span>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )
      ) : null}
    </div>
  );
}
