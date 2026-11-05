"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { useSession } from "../session-provider";
import { useT } from "@/lib/i18n";
import {
  QuizApi,
  type QuizItemTeacher,
  type QuizSettings,
} from "@/lib/api/quiz";
import {
  canPublish,
  isPublishedLocked,
  quizDraftProblems,
} from "./quiz-validation";
import { LoadingCard, EmptyCard, ErrorNotice } from "../ui";
import { Button } from "../ui/button";
import { PageBanner } from "../page-banner";
import { PageAction } from "../page-action";
import { LIST_CARD_LIFT } from "../agent-chrome";

const ITEM_TYPE_LABELS = {
  single: "Single choice",
  multiple: "Multiple choice",
  short_text: "Short text",
  long_text: "Long text",
} as const;

type NewItemType = keyof typeof ITEM_TYPE_LABELS;

function newItem(type: NewItemType): QuizItemTeacher {
  if (type === "single" || type === "multiple") {
    return {
      id: crypto.randomUUID(),
      type,
      prompt: "",
      choices: [
        { id: crypto.randomUUID(), label: "" },
        { id: crypto.randomUUID(), label: "" },
      ],
      answer: { choice_ids: [] },
      points: 1,
      required: true,
    };
  }
  return {
    id: crypto.randomUUID(),
    type,
    prompt: "",
    choices: [],
    answer: null,
    points: 1,
    required: true,
  };
}

const DEFAULT_SETTINGS: QuizSettings = {
  shuffle_questions: false,
  shuffle_choices: false,
  allow_skip: true,
  time_limit_sec: null,
};

export function QuizEditor({ quizId }: { quizId?: string }) {
  const { api, user } = useSession();
  const router = useRouter();
  const quizApi = useMemo(() => new QuizApi(api), [api]);

  const courseId =
    user?.courses.find((m) => m.role === "teacher")?.course_id ?? null;

  const [title, setTitle] = useState("");
  const [items, setItems] = useState<QuizItemTeacher[]>([]);
  const [status, setStatus] = useState("draft");
  const [loading, setLoading] = useState(Boolean(quizId));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [problems, setProblems] = useState<string[]>([]);

  const locked = isPublishedLocked(status);

  useEffect(() => {
    if (!quizId || !courseId) return;
    let alive = true;
    quizApi
      .getQuiz(courseId, quizId)
      .then((quiz) => {
        if (!alive) return;
        setTitle(quiz.title);
        setStatus(quiz.status);
        // Teacher DTO answer keys may be absent for text items; normalize so
        // the editor always edits defined fields.
        setItems(
          quiz.items.map((item) => ({
            ...item,
            required: item.required ?? true,
            points: item.points ?? 1,
            answer: item.answer ?? null,
          })),
        );
      })
      .catch((err) => {
        if (alive) setError(err);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [quizApi, quizId, courseId]);

  const patchItem = (index: number, patch: Partial<QuizItemTeacher>) => {
    setItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    );
  };

  const setAnswerIds = (item: QuizItemTeacher, ids: string[]) => {
    return { ...item, answer: { ...item.answer, choice_ids: ids } };
  };

  const toggleChoiceId = (index: number, choiceId: string, single: boolean) => {
    const item = items[index];
    const current = item.answer?.choice_ids ?? [];
    const next = single
      ? [choiceId]
      : current.includes(choiceId)
        ? current.filter((id) => id !== choiceId)
        : [...current, choiceId];
    patchItem(index, { answer: { choice_ids: next } });
  };

  const addChoice = (index: number) => {
    const item = items[index];
    patchItem(index, {
      choices: [
        ...item.choices,
        { id: crypto.randomUUID(), label: "" },
      ],
    });
  };

  const removeChoice = (index: number, choiceId: string) => {
    const item = items[index];
    patchItem(index, {
      ...setAnswerIds(
        item,
        (item.answer?.choice_ids ?? []).filter((id) => id !== choiceId),
      ),
      choices: item.choices.filter((c) => c.id !== choiceId),
    });
  };

  const save = useCallback(async (): Promise<string> => {
    if (!courseId) throw new Error("No teacher course.");
    const payload = { title: title.trim(), items, settings: DEFAULT_SETTINGS };
    if (quizId) {
      await quizApi.patchQuiz(courseId, quizId, payload);
      return quizId;
    }
    const created = await quizApi.createQuiz(courseId, payload);
    return created.id;
  }, [courseId, items, quizApi, quizId, title]);

  const onSave = async () => {
    const draftProblems = quizDraftProblems(title, items);
    setProblems(draftProblems);
    if (draftProblems.length > 0) return;
    setBusy(true);
    setError(null);
    try {
      await save();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const onDone = async () => {
    const draftProblems = quizDraftProblems(title, items);
    if (draftProblems.length > 0 || !canPublish(title, items)) {
      setProblems(
        draftProblems.length > 0
          ? draftProblems
          : ["Every choice question needs at least one marked answer."],
      );
      return;
    }
    setProblems([]);
    setBusy(true);
    setError(null);
    try {
      if (!courseId) throw new Error("No teacher course.");
      const id = await save();
      await quizApi.publishQuiz(courseId, id);
      router.push("/teacher/quizzes");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const onUnpublish = async () => {
    if (!quizId || !courseId) return;
    setBusy(true);
    setError(null);
    try {
      await quizApi.unpublishQuiz(courseId, quizId);
      setStatus("draft");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  if (!courseId) {
    return (
      <EmptyCard title="No teacher course">
        You need a teacher course before editing quizzes.
      </EmptyCard>
    );
  }

  if (loading) return <LoadingCard />;

  const disabled = locked || busy;

  return (
    <div className="space-y-4">
      <PageBanner title={title || "New quiz"}>
        <PageAction
          name="back"
          href="/teacher/quizzes"
          placement="page"
        />
        {locked ? (
          <Button onClick={onUnpublish} disabled={busy} busy={busy}>
            Unpublish
          </Button>
        ) : (
          <PageAction
            name="done"
            onClick={onDone}
            disabled={busy}
            busy={busy}
            placement="page"
          />
        )}
      </PageBanner>

      {error ? <ErrorNotice error={error} /> : null}
      {problems.map((problem, i) => (
        <ErrorNotice key={i} error={problem} />
      ))}

      <section className={LIST_CARD_LIFT}>
        <label className="block">
          <span className="text-sm font-extrabold">Title</span>
          <input
            className="mt-1 w-full rounded-[10px] border-[3px] border-[#111] px-3 py-2"
            value={title}
            disabled={disabled}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
      </section>

      {items.map((item, index) => (
        <section key={item.id} className={LIST_CARD_LIFT}>
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-extrabold">
              {index + 1}. {ITEM_TYPE_LABELS[item.type]}
            </span>
            {!locked && (
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() =>
                  setItems((prev) => prev.filter((it) => it.id !== item.id))
                }
              >
                Remove
              </Button>
            )}
          </div>

          <label className="mt-2 block">
            <span className="text-sm font-extrabold">Prompt</span>
            <input
              className="mt-1 w-full rounded-[10px] border-[3px] border-[#111] px-3 py-2"
              value={item.prompt}
              disabled={disabled}
              onChange={(e) => patchItem(index, { prompt: e.target.value })}
            />
          </label>

          <div className="mt-2 flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm font-extrabold">
              Points
              <input
                type="number"
                min={0}
                className="w-20 rounded-[10px] border-[3px] border-[#111] px-2 py-1"
                value={item.points ?? 1}
                disabled={disabled}
                onChange={(e) =>
                  patchItem(index, {
                    points: Math.max(0, Number(e.target.value) || 0),
                  })
                }
              />
            </label>
            <label className="flex items-center gap-2 text-sm font-extrabold">
              <input
                type="checkbox"
                checked={item.required ?? true}
                disabled={disabled}
                onChange={(e) =>
                  patchItem(index, { required: e.target.checked })
                }
              />
              Required
            </label>
          </div>

          {(item.type === "single" || item.type === "multiple") && (
            <>
              <div className="mt-2 space-y-2">
                {item.choices.map((choice) => {
                  const answerIds = item.answer?.choice_ids ?? [];
                  const checked = answerIds.includes(choice.id);
                  return (
                    <div key={choice.id} className="flex items-center gap-2">
                      <input
                        type={item.type === "single" ? "radio" : "checkbox"}
                        name={`quiz-item-${item.id}-answer`}
                        checked={checked}
                        disabled={disabled}
                        onChange={() =>
                          toggleChoiceId(index, choice.id, item.type === "single")
                        }
                        aria-label="Mark as correct answer"
                      />
                      <input
                        className="flex-1 rounded-[10px] border-[3px] border-[#111] px-3 py-1"
                        value={choice.label}
                        disabled={disabled}
                        onChange={(e) =>
                          patchItem(index, {
                            choices: item.choices.map((c) =>
                              c.id === choice.id
                                ? { ...c, label: e.target.value }
                                : c,
                            ),
                          })
                        }
                      />
                      {!locked && (
                        <Button
                          variant="ghost"
                          disabled={busy}
                          onClick={() => removeChoice(index, choice.id)}
                        >
                          ×
                        </Button>
                      )}
                    </div>
                  );
                })}
              </div>
              {!locked && (
                <Button
                  variant="ghost"
                  className="mt-2"
                  disabled={busy}
                  onClick={() => addChoice(index)}
                >
                  Add choice
                </Button>
              )}
            </>
          )}

          {(item.type === "short_text" || item.type === "long_text") && (
            <label className="mt-2 block">
              <span className="text-sm font-extrabold">Grading rubric</span>
              <textarea
                className="mt-1 w-full rounded-[10px] border-[3px] border-[#111] px-3 py-2"
                value={item.answer?.rubric ?? ""}
                disabled={disabled}
                onChange={(e) =>
                  patchItem(index, {
                    answer: { rubric: e.target.value },
                  })
                }
              />
            </label>
          )}
        </section>
      ))}

      {!locked && (
        <div className="flex flex-wrap items-center gap-2">
          {(Object.keys(ITEM_TYPE_LABELS) as NewItemType[]).map((type) => (
            <Button key={type} disabled={busy} onClick={() => setItems((prev) => [...prev, newItem(type)])}>
              Add {ITEM_TYPE_LABELS[type]}
            </Button>
          ))}
          <Button variant="neutral" disabled={busy} busy={busy} onClick={onSave}>
            Save
          </Button>
        </div>
      )}
    </div>
  );
}

export default QuizEditor;
