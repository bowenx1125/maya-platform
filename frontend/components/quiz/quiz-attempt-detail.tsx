"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  QuizApi,
  type QuizAttemptDetail,
  type QuizAttemptItem,
} from "../../lib/api/quiz";
import { useT } from "../../lib/i18n";
import { useSession } from "../session-provider";
import { ErrorNotice, LoadingCard } from "../ui";
import { Button } from "../ui/button";

const CELL =
  "overflow-wrap-anywhere border-b border-[#EBE5DF] px-2.5 py-2 align-top";
const HEAD = "bg-[#F7F2EA] px-2.5 py-2 text-left font-semibold text-[#625E59]";

type Draft = Record<string, { points: string; feedback: string }>;

function isText(item: QuizAttemptItem): boolean {
  return item.type === "short_text" || item.type === "long_text";
}

function choiceLabels(item: QuizAttemptItem, ids: string[] | null | undefined) {
  const byId = new Map(item.choices.map((choice) => [choice.id, choice.label]));
  return (ids ?? []).map((id) => byId.get(id) ?? id).join(" / ");
}

function draftFrom(detail: QuizAttemptDetail): Draft {
  const draft: Draft = {};
  for (const item of detail.items) {
    if (!isText(item)) continue;
    draft[item.id] = {
      points:
        item.graded && item.points_awarded != null
          ? String(item.points_awarded)
          : "",
      feedback: item.feedback ?? "",
    };
  }
  return draft;
}

/**
 * One submitted quiz attempt, read from the paper it answered. A teacher
 * sees the key, grades text questions by hand (no model call) and can hide
 * the attempt; a student sees their own answers, results and feedback only.
 */
export function QuizAttemptDetailView({
  courseId,
  quizId,
  attemptId,
  teacher,
  onChanged,
  onHidden,
}: {
  courseId: string;
  quizId: string;
  attemptId: string;
  teacher: boolean;
  /** A grade was saved: the list's score is stale. */
  onChanged?: () => void;
  /** The attempt was hidden: the list should drop it. */
  onHidden?: () => void;
}) {
  const t = useT();
  const { api } = useSession();
  const quizApi = useMemo(() => new QuizApi(api), [api]);
  const [detail, setDetail] = useState<QuizAttemptDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [hiding, setHiding] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const next = await quizApi.getAttempt(courseId, quizId, attemptId);
      setDetail(next);
      setDraft(draftFrom(next));
    } catch (cause) {
      setError(cause);
    }
  }, [attemptId, courseId, quizApi, quizId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const save = async () => {
    if (!detail) return;
    const grades = detail.items
      .filter((item) => isText(item) && draft[item.id]?.points.trim())
      .map((item) => ({
        item_id: item.id,
        points_awarded: Number(draft[item.id].points),
        feedback: draft[item.id].feedback,
      }));
    if (!grades.length) return;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const next = await quizApi.gradeAttempt(
        courseId,
        quizId,
        attemptId,
        grades,
      );
      setDetail(next);
      setDraft(draftFrom(next));
      setSaved(true);
      onChanged?.();
    } catch (cause) {
      setError(cause);
    } finally {
      setSaving(false);
    }
  };

  const hide = async () => {
    if (!detail || hiding || !window.confirm(t("quizHideConfirm"))) return;
    setHiding(true);
    setError(null);
    try {
      await quizApi.hideAttempt(courseId, quizId, attemptId);
      onHidden?.();
    } catch (cause) {
      setError(cause);
      setHiding(false);
    }
  };

  if (!detail) {
    return error ? (
      <ErrorNotice inline error={error} onRetry={() => void load()} />
    ) : (
      <LoadingCard size="sm" />
    );
  }

  const gradable = teacher && detail.items.some(isText);
  return (
    <div className="grid gap-2" data-testid="quiz-attempt-detail">
      <div className="flex flex-wrap items-center gap-2 font-body text-xs font-bold text-[#555]">
        <span>{t("quizRound", { n: detail.taking_epoch })}</span>
        <span>
          · {detail.points_awarded} / {detail.points_total}
        </span>
        {detail.grading_status !== "complete" ? (
          <span className="rounded-full border-2 border-black bg-[#FDE68A] px-2 py-px text-black">
            {t("quizNeedsGrading")}
          </span>
        ) : null}
      </div>
      <div className="overflow-x-auto rounded-[10px] border border-[#EBE5DF] bg-[#FFFDF8]">
        <table className="w-full min-w-[560px] border-collapse font-body text-xs">
          <thead>
            <tr>
              <th scope="col" className={HEAD}>
                #
              </th>
              <th scope="col" className={HEAD}>
                {t("overviewQuestion")}
              </th>
              <th scope="col" className={HEAD}>
                {t("overviewAnswer")}
              </th>
              {teacher ? (
                <th scope="col" className={HEAD}>
                  {t("quizAnswerKey")}
                </th>
              ) : null}
              <th scope="col" className={HEAD}>
                {t("overviewPoints")}
              </th>
              <th scope="col" className={HEAD}>
                {t("overviewFeedback")}
              </th>
            </tr>
          </thead>
          <tbody>
            {detail.items.map((item, index) => {
              const n = index + 1;
              const text = isText(item);
              const answer = text
                ? item.response_text?.trim() || t("overviewNotAnswered")
                : choiceLabels(item, item.response_choice_ids) ||
                  t("overviewNotAnswered");
              return (
                <tr key={item.id}>
                  <td className={`${CELL} w-[2ch] text-[#625E59]`}>{n}</td>
                  <td className={CELL}>{item.prompt}</td>
                  <td className={CELL}>
                    {answer}
                    {!text && item.correct != null ? (
                      <span className="ml-1.5 font-extrabold">
                        ({item.correct ? t("quizCorrect") : t("quizIncorrect")})
                      </span>
                    ) : null}
                  </td>
                  {teacher ? (
                    <td className={CELL}>
                      {text
                        ? (item.answer?.rubric ?? "")
                        : choiceLabels(item, item.answer?.choice_ids)}
                    </td>
                  ) : null}
                  <td className={CELL}>
                    {text && teacher ? (
                      <span className="inline-flex items-center gap-1">
                        <input
                          type="number"
                          inputMode="decimal"
                          min={0}
                          max={item.points}
                          step="any"
                          aria-label={t("quizGradePointsFor", { n })}
                          className="w-16 rounded-md border-2 border-black bg-white px-1.5 py-1"
                          value={draft[item.id]?.points ?? ""}
                          onChange={(event) =>
                            setDraft((current) => ({
                              ...current,
                              [item.id]: {
                                feedback: current[item.id]?.feedback ?? "",
                                points: event.target.value,
                              },
                            }))
                          }
                        />
                        / {item.points}
                      </span>
                    ) : text && !item.graded ? (
                      t("quizNotGraded")
                    ) : (
                      `${item.points_awarded ?? 0} / ${item.points}`
                    )}
                  </td>
                  <td className={CELL}>
                    {text && teacher ? (
                      <textarea
                        aria-label={t("quizGradeFeedbackFor", { n })}
                        className="min-h-14 w-full min-w-40 rounded-md border-2 border-black bg-white px-1.5 py-1"
                        maxLength={4000}
                        value={draft[item.id]?.feedback ?? ""}
                        onChange={(event) =>
                          setDraft((current) => ({
                            ...current,
                            [item.id]: {
                              points: current[item.id]?.points ?? "",
                              feedback: event.target.value,
                            },
                          }))
                        }
                      />
                    ) : (
                      (item.feedback ?? "")
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {error ? <ErrorNotice inline error={error} /> : null}
      {saved ? (
        <p
          className="m-0 font-body text-xs font-bold text-[#16A34A]"
          role="status"
        >
          {t("quizGradesSaved")}
        </p>
      ) : null}
      {teacher ? (
        <div className="flex flex-wrap justify-end gap-2">
          {gradable ? (
            <Button
              type="button"
              disabled={saving}
              busy={saving}
              onClick={() => void save()}
            >
              {t("quizSaveGrades")}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="neutral"
            disabled={hiding}
            busy={hiding}
            aria-label={t("quizHideAttemptNamed", {
              name: detail.student_name,
            })}
            onClick={() => void hide()}
          >
            {t("quizHideAttempt")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
