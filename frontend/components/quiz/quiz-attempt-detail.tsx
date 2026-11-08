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
import { WorkspaceIcon } from "../workspace-icon";
import { KEY_ROW, QuizKey } from "../quizzes/quiz-chrome";
import {
  isFiniteScore,
  quizGradingStatusLabel,
} from "../quizzes/quiz-validation";

const CELL =
  "overflow-wrap-anywhere border-b-2 border-[#E5E7EB] px-2.5 py-3 align-top";
const HEAD =
  "border-b-[3px] border-border px-2.5 py-2 text-left text-xs font-extrabold text-arc-muted";

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
    // A's "marked paper" (owner pick 2026-11-08): ruled paper with a red
    // margin, right/wrong rows marked like a teacher's pen.
    <div
      className="relative grid gap-3 rounded-[4px_4px_16px_16px] border-[3px] border-border bg-white bg-[linear-gradient(90deg,transparent_38px,#FCA5A5_38px,#FCA5A5_40px,transparent_40px)] pt-14 pb-5 pr-[clamp(12px,3vw,28px)] pl-[52px] shadow-arc max-[520px]:pl-[48px]"
      data-testid="quiz-attempt-detail"
    >
      <span
        className="absolute top-3 right-5 inline-block -rotate-3 font-display text-[34px] leading-none font-extrabold text-[#DC2626]"
        aria-label={`${detail.points_awarded} / ${detail.points_total}`}
      >
        {detail.points_awarded} / {detail.points_total}
      </span>
      {teacher ? (
        <div className="flex flex-wrap items-center gap-2 pr-24">
          <span
            data-testid="quiz-grading-status"
            className={`rounded-full border-2 border-border px-3 py-1 text-xs font-extrabold ${
              detail.grading_status === "complete"
                ? "bg-[#ECFCCB]"
                : "bg-warn-bg"
            }`}
          >
            {quizGradingStatusLabel(detail.grading_status)}
          </span>
          {isFiniteScore(detail.score_ai) ? (
            <span
              data-testid="quiz-score-ai"
              className="font-body text-sm font-extrabold"
            >
              AI score: {detail.score_ai}
            </span>
          ) : null}
        </div>
      ) : null}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] border-collapse font-body text-sm text-ink">
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
              const tint =
                !text && item.correct === true
                  ? "bg-[#ECFCCB]"
                  : !text && item.correct === false
                    ? "bg-err-bg"
                    : "";
              return (
                <tr key={item.id} className={tint}>
                  <td className={`${CELL} w-[2ch] font-mono font-bold`}>{n}</td>
                  <td className={CELL}>{item.prompt}</td>
                  <td className={`${CELL} font-semibold`}>
                    {answer}
                    {!text && item.correct != null ? (
                      <span
                        className={`ml-2 inline-flex items-center gap-1 font-display font-extrabold whitespace-nowrap ${item.correct ? "text-[#15803D]" : "text-err-text"}`}
                      >
                        <WorkspaceIcon
                          name={item.correct ? "done" : "close"}
                          size={16}
                          stroke={3.2}
                        />
                        {item.correct ? t("quizCorrect") : t("quizIncorrect")}
                      </span>
                    ) : null}
                  </td>
                  {teacher ? (
                    <td className={`${CELL} text-arc-muted`}>
                      {text
                        ? (item.answer?.rubric ?? "")
                        : choiceLabels(item, item.answer?.choice_ids)}
                    </td>
                  ) : null}
                  <td
                    className={`${CELL} font-mono font-bold whitespace-nowrap`}
                  >
                    {text && teacher ? (
                      <span className="inline-flex flex-col items-start gap-1">
                        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                          <input
                            type="number"
                            inputMode="decimal"
                            min={0}
                            max={item.points}
                            step="any"
                            aria-label={t("quizGradePointsFor", { n })}
                            className="min-h-11 w-16 rounded-arc border-[3px] border-border bg-white px-2 font-mono text-base font-bold focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-main"
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
                        {isFiniteScore(item.ai_score) ? (
                          <span data-testid={`quiz-item-ai-score-${item.id}`}>
                            AI score: {item.ai_score}
                          </span>
                        ) : detail.grading_status !== "complete" &&
                          !item.graded ? (
                          <span data-testid={`quiz-item-ai-pending-${item.id}`}>
                            Pending
                          </span>
                        ) : null}
                      </span>
                    ) : text && !item.graded ? (
                      <span className="font-body font-semibold text-arc-muted">
                        {t("quizNotGraded")}
                      </span>
                    ) : (
                      `${item.points_awarded ?? 0} / ${item.points}`
                    )}
                  </td>
                  <td className={CELL}>
                    {text && teacher ? (
                      <textarea
                        aria-label={t("quizGradeFeedbackFor", { n })}
                        className="min-h-16 w-full min-w-44 rounded-arc border-[3px] border-border bg-white px-2.5 py-2 font-body text-sm focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-main"
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
          className="m-0 font-body text-sm font-extrabold text-[#15803D]"
          role="status"
        >
          {t("quizGradesSaved")}
        </p>
      ) : null}
      {teacher ? (
        // Save comes first in the DOM so Tab runs Grade → Comment → Save
        // (handoff §5); row-reverse keeps Save on the right.
        <div className={`flex-row-reverse justify-start ${KEY_ROW}`}>
          {gradable ? (
            <QuizKey
              icon="done"
              tone="primary"
              busy={saving}
              onClick={() => void save()}
            >
              {t("quizSaveGrades")}
            </QuizKey>
          ) : null}
          <QuizKey
            icon="eyeOff"
            busy={hiding}
            ariaLabel={t("quizHideAttemptNamed", {
              name: detail.student_name,
            })}
            onClick={() => void hide()}
          >
            {t("quizHideAttempt")}
          </QuizKey>
        </div>
      ) : null}
    </div>
  );
}
