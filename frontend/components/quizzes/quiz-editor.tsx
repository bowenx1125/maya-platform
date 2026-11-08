"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
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
import { LoadingCard, ErrorNotice } from "../ui";
import { ICON_MOTION } from "../ui/button";
import { IconLock } from "../quiet-icons";
import { WorkspaceIcon } from "../workspace-icon";
import {
  KEY_ROW,
  QuizEmpty,
  QuizKey,
  QuizStatus,
  QuizTabs,
  quizState,
} from "./quiz-chrome";
import { QuizSubmissions } from "./quiz-submissions";
import { PageBanner } from "../page-banner";
import { PageAction } from "../page-action";
import { beginDoneLock, releaseDoneLock } from "@/lib/quiz-gate";
import { celebrate } from "@/lib/confetti";

export type QuizPageTab = "paper" | "submissions";

function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noreferrer";
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

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

/**
 * One page per quiz (option A, 2026-11-08). Paper is the question sheet:
 * editable while a draft, read-only once published. Submissions is the
 * quiz's record: every student attempt, graded here. A new or never-taken
 * draft keeps Submissions locked, so the two never look alike.
 */
export function QuizEditor({
  quizId,
  initialTab,
}: {
  quizId?: string;
  initialTab?: QuizPageTab;
}) {
  const { api, user } = useSession();
  const t = useT();
  const router = useRouter();
  const quizApi = useMemo(() => new QuizApi(api), [api]);

  const courseId =
    user?.courses.find((m) => m.role === "teacher")?.course_id ?? null;

  const [title, setTitle] = useState("");
  const [items, setItems] = useState<QuizItemTeacher[]>([]);
  const [status, setStatus] = useState("draft");
  const [loading, setLoading] = useState(Boolean(quizId));
  const [busy, setBusy] = useState(false);
  const doneLock = useRef(false);
  const [error, setError] = useState<unknown>(null);
  const [takingOpen, setTakingOpen] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const [tab, setTab] = useState<QuizPageTab | null>(initialTab ?? null);
  const [attemptCount, setAttemptCount] = useState(0);
  const [exportBusy, setExportBusy] = useState(false);

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
        setTakingOpen(quiz.taking_open === true);
        setAttemptCount(quiz.attempt_count ?? 0);
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
      choices: [...item.choices, { id: crypto.randomUUID(), label: "" }],
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

  const onDone = async () => {
    if (!beginDoneLock(doneLock)) return;
    const draftProblems = quizDraftProblems(title, items);
    if (draftProblems.length > 0 || !canPublish(title, items)) {
      setProblems(
        draftProblems.length > 0
          ? draftProblems
          : ["Every choice question needs at least one marked answer."],
      );
      releaseDoneLock(doneLock);
      return;
    }
    setProblems([]);
    setBusy(true);
    setError(null);
    try {
      if (!courseId) throw new Error("No teacher course.");
      const id = await save();
      await quizApi.publishQuiz(courseId, id);
      celebrate();
      router.push("/teacher/quizzes");
      // Keep doneLock held after success so remount/nav cannot double-fire.
    } catch (err) {
      setError(err);
      releaseDoneLock(doneLock);
      setBusy(false);
    }
  };

  const onToggleEvaluation = async (next: "start" | "pause") => {
    if (!quizId || !courseId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const updated =
        next === "start"
          ? await quizApi.startTaking(courseId, quizId)
          : await quizApi.pauseTaking(courseId, quizId);
      setTakingOpen(updated.taking_open === true);
      setStatus(updated.status);
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
      // The server closes taking on unpublish; mirror it.
      setTakingOpen(false);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const onExport = async () => {
    if (!quizId || !courseId) return;
    setExportBusy(true);
    setError(null);
    try {
      const result = await quizApi.exportAttempts(courseId, quizId);
      triggerBlobDownload(result.blob, result.filename);
    } catch (err) {
      setError(err);
    } finally {
      setExportBusy(false);
    }
  };

  if (!courseId) {
    return <QuizEmpty title={t("quizNoCourse")} kind="course" />;
  }

  if (loading) return <LoadingCard />;

  const state = quizState({ status, taking_open: takingOpen });
  const hasRecord = Boolean(quizId) && (locked || attemptCount > 0);
  const view: QuizPageTab = hasRecord
    ? (tab ?? (locked ? "submissions" : "paper"))
    : "paper";
  const stateLabel =
    state === "accepting"
      ? t("quizAccepting")
      : state === "paused"
        ? t("quizPaused")
        : t("quizDraft");

  return (
    <div className="space-y-6">
      {/* A long quiz title wraps and pushes the keys to a second row rather
          than past the banner's edge. A draft's title is typed in place. */}
      <PageBanner
        title={
          locked ? (
            title
          ) : (
            <label className="block">
              <span className="sr-only">Title</span>
              <input
                className="w-full min-w-0 border-0 border-b-[3px] border-dashed border-border bg-transparent px-1.5 font-[inherit] text-inherit placeholder:text-[#9CA3AF] focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-main"
                value={title}
                placeholder={t("quizEditorNew")}
                disabled={busy}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
          )
        }
        className="flex-wrap gap-y-4"
        titleClassName="min-w-0 flex-[1_1_480px] break-words"
        actionsClassName="min-w-0 flex-[0_1_auto] flex-wrap justify-end"
      >
        <QuizStatus state={state} label={stateLabel} />
        <PageAction
          name="back"
          href="/teacher/quizzes"
          placement="page"
          className="relative"
        />
        {locked ? (
          takingOpen ? (
            <QuizKey
              icon="pause"
              busy={busy}
              onClick={() => void onToggleEvaluation("pause")}
            >
              {t("quizPauseEvaluation")}
            </QuizKey>
          ) : (
            <QuizKey
              icon="play"
              tone="primary"
              busy={busy}
              onClick={() => void onToggleEvaluation("start")}
            >
              {t("quizStartEvaluation")}
            </QuizKey>
          )
        ) : view === "paper" ? (
          <PageAction
            name="done"
            onClick={onDone}
            disabled={busy}
            busy={busy}
            placement="page"
            className="relative"
          />
        ) : null}
        {hasRecord ? (
          <QuizKey
            icon="download"
            busy={exportBusy}
            onClick={() => void onExport()}
            testId="quiz-export-download"
            guide="quiz.exportDownload"
          >
            {t("download")}
          </QuizKey>
        ) : null}
      </PageBanner>

      <QuizTabs<QuizPageTab>
        label="Quiz"
        value={view}
        onChange={setTab}
        tabs={[
          { value: "paper", label: t("quizTabPaper") },
          {
            value: "submissions",
            label: t("quizTabSubmissions"),
            count: hasRecord ? attemptCount : undefined,
            lockedReason: hasRecord
              ? undefined
              : t("quizSubmissionsLockedReason"),
          },
        ]}
      />

      {error ? <ErrorNotice error={error} /> : null}
      {problems.map((problem, i) => (
        <ErrorNotice key={i} error={problem} />
      ))}

      {view === "submissions" && quizId ? (
        <QuizSubmissions
          courseId={courseId}
          quizId={quizId}
          onCount={setAttemptCount}
        />
      ) : locked ? (
        <>
          <div className="flex flex-wrap items-center gap-3 rounded-[14px] border-[3px] border-border bg-warn-bg px-[18px] py-3 font-body text-sm font-bold text-ink shadow-[4px_4px_0_#FACC15]">
            <p
              role="status"
              className="m-0 flex flex-[1_1_240px] items-center gap-3"
            >
              <IconLock size={18} />
              {t("quizPublishedLocked")}
            </p>
            <div className={KEY_ROW}>
              <QuizKey
                icon="undo"
                busy={busy}
                onClick={() => void onUnpublish()}
              >
                {t("quizUnpublish")}
              </QuizKey>
            </div>
          </div>
          {items.map((item, index) => (
            <QuestionCard key={item.id} item={item} index={index}>
              <p className="m-0 font-body text-lg font-bold text-ink">
                {item.prompt}
              </p>
              {isChoice(item) ? (
                <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3 p-0">
                  {item.choices.map((choice) => {
                    const correct = (item.answer?.choice_ids ?? []).includes(
                      choice.id,
                    );
                    return (
                      <li
                        key={choice.id}
                        className={`flex min-h-12 items-center gap-2.5 rounded-arc border-[3px] border-border px-3.5 font-body font-bold text-ink ${correct ? "bg-[#D9F99D]" : "bg-white"}`}
                      >
                        {correct ? <CorrectTick /> : null}
                        {choice.label}
                        {correct ? (
                          <span className="sr-only">
                            ({t("quizAnswerKey")})
                          </span>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="m-0 rounded-arc border-2 border-dashed border-border bg-[#FAF5FF] px-3.5 py-3 font-body text-sm text-ink">
                  <b>Grading rubric</b> · {item.answer?.rubric ?? ""}
                </p>
              )}
            </QuestionCard>
          ))}
        </>
      ) : (
        <>
          {items.map((item, index) => (
            <QuestionCard
              key={item.id}
              item={item}
              index={index}
              action={
                <QuizKey
                  icon="close"
                  disabled={busy}
                  onClick={() =>
                    setItems((prev) => prev.filter((it) => it.id !== item.id))
                  }
                >
                  Remove
                </QuizKey>
              }
            >
              <label className="flex flex-col gap-2 font-body text-sm font-extrabold text-ink">
                Prompt
                <input
                  className="min-h-11 rounded-arc border-[3px] border-border bg-white px-3.5 font-body text-base font-semibold"
                  value={item.prompt}
                  disabled={busy}
                  onChange={(e) => patchItem(index, { prompt: e.target.value })}
                />
              </label>

              <div className="flex flex-wrap items-center gap-5">
                <PointsStepper
                  id={`quiz-points-${item.id}`}
                  value={item.points ?? 1}
                  disabled={busy}
                  onChange={(points) => patchItem(index, { points })}
                />
                <label className="flex items-center gap-2 font-body text-sm font-extrabold text-ink">
                  <input
                    type="checkbox"
                    className="size-5 accent-[#FF4D8D]"
                    checked={item.required ?? true}
                    disabled={busy}
                    onChange={(e) =>
                      patchItem(index, { required: e.target.checked })
                    }
                  />
                  Required
                </label>
              </div>

              {isChoice(item) ? (
                <>
                  <div className="grid gap-3">
                    {item.choices.map((choice, choiceIndex) => {
                      const checked = (item.answer?.choice_ids ?? []).includes(
                        choice.id,
                      );
                      return (
                        <div
                          key={choice.id}
                          className={`flex items-center gap-2.5 rounded-[12px] border-[3px] border-border p-1.5 ${checked ? "bg-[#ECFCCB]" : "bg-white"}`}
                        >
                          {/* The real radio/checkbox stays in the label, so
                              tests and screen readers keep "Mark as correct
                              answer"; the lime tile is its visible face. */}
                          <label
                            className={`grid size-10 shrink-0 cursor-pointer place-items-center rounded-[8px] border-[3px] border-border text-ink has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-main ${checked ? "bg-[#A3E635]" : "bg-white"}`}
                          >
                            <input
                              type={
                                item.type === "single" ? "radio" : "checkbox"
                              }
                              name={`quiz-item-${item.id}-answer`}
                              className="sr-only"
                              checked={checked}
                              disabled={busy}
                              onChange={() =>
                                toggleChoiceId(
                                  index,
                                  choice.id,
                                  item.type === "single",
                                )
                              }
                              aria-label="Mark as correct answer"
                            />
                            <span className={checked ? "" : "opacity-15"}>
                              <WorkspaceIcon
                                name="done"
                                size={18}
                                stroke={3.2}
                              />
                            </span>
                          </label>
                          <input
                            aria-label={`Choice ${choiceIndex + 1}`}
                            className="min-h-10 min-w-0 flex-1 rounded-[8px] border-2 border-transparent bg-transparent px-2 font-body text-base font-bold focus:border-border focus:bg-white"
                            value={choice.label}
                            disabled={busy}
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
                          <button
                            type="button"
                            aria-label={`Remove choice ${choiceIndex + 1}`}
                            className={`grid size-10 shrink-0 cursor-pointer place-items-center rounded-[8px] text-ink ${ICON_MOTION}`}
                            disabled={busy}
                            onClick={() => removeChoice(index, choice.id)}
                          >
                            <WorkspaceIcon
                              name="close"
                              size={16}
                              stroke={2.6}
                            />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                  <div>
                    <QuizKey
                      icon="new"
                      disabled={busy}
                      onClick={() => addChoice(index)}
                    >
                      Add choice
                    </QuizKey>
                  </div>
                </>
              ) : (
                <label className="flex flex-col gap-2 font-body text-sm font-extrabold text-ink">
                  Grading rubric
                  <textarea
                    className="min-h-[72px] rounded-arc border-[3px] border-border bg-white px-3.5 py-2.5 font-body text-[15px] font-medium"
                    value={item.answer?.rubric ?? ""}
                    disabled={busy}
                    onChange={(e) =>
                      patchItem(index, {
                        answer: { rubric: e.target.value },
                      })
                    }
                  />
                </label>
              )}
            </QuestionCard>
          ))}

          {/* B's dashed "Add question" slot (owner pick) in A's colours. */}
          <section className="flex flex-col items-center gap-3.5 rounded-2xl border-[3px] border-dashed border-border bg-white/45 px-5 py-6">
            <span
              aria-hidden="true"
              className="grid size-14 place-items-center rounded-[14px] border-[3px] border-border bg-white text-ink shadow-[4px_4px_0_#111]"
            >
              <WorkspaceIcon name="new" size={30} stroke={3} />
            </span>
            <h2 className="m-0 font-body text-[15px] font-extrabold text-ink">
              {t("quizAddQuestion")}
            </h2>
            <div className="flex flex-wrap justify-center gap-2.5">
              {(Object.keys(ITEM_TYPE_LABELS) as NewItemType[]).map((type) => (
                <QuizKey
                  key={type}
                  icon="new"
                  disabled={busy}
                  className={
                    type === "single" || type === "multiple"
                      ? "bg-[#CFFAFE]"
                      : "bg-[#EDE9FE]"
                  }
                  onClick={() => setItems((prev) => [...prev, newItem(type)])}
                >
                  {ITEM_TYPE_LABELS[type]}
                </QuizKey>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function isChoice(item: QuizItemTeacher): boolean {
  return item.type === "single" || item.type === "multiple";
}

function CorrectTick() {
  return (
    <span
      aria-hidden="true"
      className="grid size-6 shrink-0 place-items-center rounded-md border-2 border-border bg-[#A3E635] text-ink"
    >
      <WorkspaceIcon name="done" size={14} stroke={3.4} />
    </span>
  );
}

/** A's worksheet card: mono number, type pill, ruled paper by type. */
function QuestionCard({
  item,
  index,
  action,
  children,
}: {
  item: QuizItemTeacher;
  index: number;
  action?: ReactNode;
  children: ReactNode;
}) {
  const choice = isChoice(item);
  return (
    <section
      className={`flex flex-col gap-4 rounded-2xl border-[3px] border-border bg-white px-6 py-[22px] ${
        choice
          ? "bg-[repeating-linear-gradient(#FFFFFF_0_31px,#E0F2FE_31px_32px)] shadow-[6px_6px_0_#67E8F9]"
          : "bg-[repeating-linear-gradient(#FFFFFF_0_31px,#F3E8FF_31px_32px)] shadow-[6px_6px_0_#C4B5FD]"
      }`}
    >
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-xl font-bold text-[#6B7280]">
          #{String(index + 1).padStart(2, "0")}
        </span>
        <span
          className={`rounded-full border-2 border-border px-3 py-1 font-body text-xs font-extrabold text-ink ${choice ? "bg-[#CFFAFE]" : "bg-[#EDE9FE]"}`}
        >
          {ITEM_TYPE_LABELS[item.type as NewItemType]}
        </span>
        {action ? (
          <span className="ml-auto">{action}</span>
        ) : (
          <span className="ml-auto font-mono font-bold text-ink">
            {item.points ?? 1} {(item.points ?? 1) === 1 ? "pt" : "pts"}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}

/** Points as a stepper key (− n +); the number stays typeable. */
function PointsStepper({
  id,
  value,
  disabled,
  onChange,
}: {
  id: string;
  value: number;
  disabled?: boolean;
  onChange: (points: number) => void;
}) {
  const step = (delta: number) => onChange(Math.max(0, value + delta));
  return (
    <div className="flex items-center gap-2 font-body text-sm font-extrabold text-ink">
      <label htmlFor={id}>Points</label>
      <span className="inline-flex items-stretch overflow-hidden rounded-arc border-[3px] border-border bg-white">
        <button
          type="button"
          aria-label="Fewer points"
          className="grid w-10 cursor-pointer place-items-center border-r-[3px] border-border bg-white hover:bg-warn-bg disabled:cursor-not-allowed"
          disabled={disabled || value <= 0}
          onClick={() => step(-1)}
        >
          <WorkspaceIcon name="minus" size={16} stroke={3} />
        </button>
        <input
          id={id}
          type="number"
          min={0}
          className="h-10 w-14 border-0 text-center font-mono text-base font-bold [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(Math.max(0, Number(e.target.value) || 0))}
        />
        <button
          type="button"
          aria-label="More points"
          className="grid w-10 cursor-pointer place-items-center border-l-[3px] border-border bg-white hover:bg-warn-bg disabled:cursor-not-allowed"
          disabled={disabled}
          onClick={() => step(1)}
        >
          <WorkspaceIcon name="new" size={16} stroke={3} />
        </button>
      </span>
    </div>
  );
}

export default QuizEditor;
