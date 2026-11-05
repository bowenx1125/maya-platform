"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  sanitizeStudentQuiz,
  type PlatformApi,
  type QuizAttemptDto,
  type StudentQuizDto,
  type SubmitQuizAttemptRequest,
} from "../../lib/api";
import {
  clearQuizDraft,
  readQuizDraft,
  writeQuizDraft,
  type QuizDraft,
} from "../../lib/quiz-draft";
import { useSession } from "../session-provider";
import { ErrorNotice, LoadingCard } from "../ui";
import {
  Questionnaire,
  QuestionnaireActions,
  QuestionnaireChoice,
  QuestionnaireChoices,
  QuestionnaireInput,
  QuestionnaireItem,
  QuestionnaireProgress,
} from "../ui/questionnaire";

type TakeApi = Pick<
  PlatformApi,
  "getStudentQuiz" | "submitCourseQuizAttempt"
>;

/**
 * Take view: loads the student projection, renders the Questionnaire,
 * persists every change to the localStorage draft, and submits once. Zero
 * websocket / LLM / agent imports on purpose — a quiz is a plain form POST.
 */
export function QuizTake({
  courseId,
  quizId,
  quiz: quizProp,
  onExit,
  api: apiProp,
}: {
  courseId: string;
  /** Load this quiz when no fetched quiz is handed in. */
  quizId?: string;
  /** An already-fetched student projection skips the load. */
  quiz?: StudentQuizDto;
  onExit: () => void;
  /** Test seam; production resolves useSession().api. */
  api?: TakeApi;
}) {
  const session = useSession();
  const client = apiProp ?? (session.api as TakeApi);
  const userId = session.user?.id ?? "";
  const [quiz, setQuiz] = useState<StudentQuizDto | null>(quizProp ?? null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [answers, setAnswers] = useState<QuizDraft>(() => ({}));
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<QuizAttemptDto | null>(null);
  const [submitError, setSubmitError] = useState<unknown>(null);
  const effectiveQuizId = quizId ?? quizProp?.id ?? "";

  // Load the projection, then hydrate the saved draft.
  useEffect(() => {
    if (quizProp || !effectiveQuizId || !client) return;
    let active = true;
    setLoadError(null);
    client
      .getStudentQuiz(courseId, effectiveQuizId)
      .then((loaded) => {
        if (!active) return;
        // The mapper strips answer/rubric even if a server leaked them.
        setQuiz(sanitizeStudentQuiz(loaded));
        setAnswers(readQuizDraft(courseId, userId, effectiveQuizId) ?? {});
      })
      .catch((cause) => {
        if (active) setLoadError(cause);
      });
    return () => {
      active = false;
    };
  }, [client, courseId, effectiveQuizId, quizProp, userId]);

  const update = useCallback(
    (itemId: string, answer: QuizDraft[string] | undefined) => {
      setAnswers((current) => {
        const next = { ...current };
        if (answer === undefined) delete next[itemId];
        else next[itemId] = answer;
        if (effectiveQuizId && userId)
          writeQuizDraft(courseId, userId, effectiveQuizId, next);
        return next;
      });
    },
    [courseId, effectiveQuizId, userId],
  );

  const submit = useCallback(async () => {
    if (!quiz || !client) return;
    const body: SubmitQuizAttemptRequest = {
      answers: Object.entries(answers)
        .filter(([, answer]) => answer !== undefined)
        .map(([item_id, answer]) =>
          answer.choice_ids !== undefined
            ? { item_id, choice_ids: answer.choice_ids }
            : { item_id, text: answer.text ?? "" },
        ),
    };
    if (!body.answers.length) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const attempt = await client.submitCourseQuizAttempt(
        courseId,
        quiz.id,
        body,
      );
      // The server holds the attempt; the draft has served its purpose.
      clearQuizDraft(courseId, userId, quiz.id);
      setResult(attempt);
    } catch (cause) {
      // One-shot: never retry a charged submission automatically.
      setSubmitError(cause);
    } finally {
      setSubmitting(false);
    }
  }, [answers, client, courseId, quiz, userId]);

  const answered = useMemo(() => Object.keys(answers).length, [answers]);

  if (loadError) {
    return <ErrorNotice inline error={loadError} onRetry={onExit} />;
  }
  if (!quiz) return <LoadingCard />;
  if (result) {
    const percent =
      result.score_max_objective > 0
        ? Math.round(
            (result.score_objective / result.score_max_objective) * 100,
          )
        : null;
    return (
      <div className="rounded-[14px] border-[3px] border-border bg-white px-6 py-8 text-center shadow-[6px_6px_0_#C4B5FD]">
        <p className="m-0 inline-block -rotate-[1.5deg] rounded-md border-[3px] border-border bg-main px-[18px] py-1 font-display text-[30px] font-extrabold text-main-fg shadow-[4px_4px_0_#FFE14D]">
          Submitted
        </p>
        <p className="mt-4 font-body text-sm font-semibold text-ink">
          {percent === null
            ? "Your answers are in."
            : `Objective score: ${result.score_objective} / ${result.score_max_objective} (${percent}%)`}
        </p>
        <button
          type="button"
          onClick={onExit}
          className="mt-5 inline-flex min-h-10 cursor-pointer items-center rounded-[10px] border-[3px] border-border bg-surface px-[18px] py-2 font-body text-sm font-bold text-ink shadow-[0_6px_0_#111] transition-[translate,box-shadow] duration-150 ease-[cubic-bezier(.2,.8,.2,1)] hover:-translate-y-0.5 active:translate-y-1.5 active:shadow-none active:duration-[80ms] motion-reduce:transition-colors"
        >
          Back to quizzes
        </button>
      </div>
    );
  }

  return (
    <Questionnaire>
      <QuestionnaireProgress>
        Answered {answered} / {quiz.items.length}
      </QuestionnaireProgress>
      {submitError ? <ErrorNotice inline error={submitError} /> : null}
      {quiz.items.map((item, index) => (
        <QuestionnaireItem key={item.id}>
          <p className="m-0 font-body text-base font-extrabold text-ink">
            <span className="mr-2 font-mono text-sm text-[#9CA3AF]">
              {String(index + 1).padStart(2, "0")}
            </span>
            {item.prompt}
          </p>
          {item.type === "single" || item.type === "multiple" ? (
            <QuestionnaireChoices>
              {item.choices.map((choice) => {
                const current = answers[item.id]?.choice_ids ?? [];
                const checked = current.includes(choice.id);
                return (
                  <QuestionnaireChoice
                    key={choice.id}
                    state={{
                      type: item.type === "single" ? "radio" : "checkbox",
                      checked,
                      onSelect: () => {
                        if (item.type === "single") {
                          update(item.id, { choice_ids: [choice.id] });
                        } else {
                          update(item.id, {
                            choice_ids: checked
                              ? current.filter((id) => id !== choice.id)
                              : [...current, choice.id],
                          });
                        }
                      },
                    }}
                  >
                    {choice.label}
                  </QuestionnaireChoice>
                );
              })}
            </QuestionnaireChoices>
          ) : (
            <QuestionnaireInput
              rows={item.type === "long_text" ? 5 : 2}
              aria-label={item.prompt}
              value={answers[item.id]?.text ?? ""}
              onChange={(event) =>
                update(item.id, { text: event.target.value })
              }
            />
          )}
        </QuestionnaireItem>
      ))}
      <QuestionnaireActions>
        <button
          type="button"
          onClick={onExit}
          className="inline-flex min-h-10 cursor-pointer items-center rounded-[10px] border-[3px] border-border bg-surface px-[18px] py-2 font-body text-sm font-bold text-ink shadow-[0_6px_0_#111] transition-[translate,box-shadow] duration-150 ease-[cubic-bezier(.2,.8,.2,1)] hover:-translate-y-0.5 active:translate-y-1.5 active:shadow-none active:duration-[80ms] motion-reduce:transition-colors"
        >
          Back
        </button>
        <button
          type="button"
          disabled={submitting || !answered}
          onClick={() => void submit()}
          className="inline-flex min-h-10 cursor-pointer items-center rounded-[10px] border-[3px] border-border bg-main px-[18px] py-2 font-body text-sm font-bold text-main-fg shadow-[0_6px_0_#111] transition-[translate,box-shadow] duration-150 ease-[cubic-bezier(.2,.8,.2,1)] hover:-translate-y-0.5 active:translate-y-1.5 active:shadow-none active:duration-[80ms] motion-reduce:transition-colors disabled:pointer-events-none disabled:opacity-50"
        >
          {submitting ? "Submitting…" : "Submit"}
        </button>
      </QuestionnaireActions>
    </Questionnaire>
  );
}
