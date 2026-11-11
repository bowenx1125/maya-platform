"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEventHandler,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

import {
  QuizApi,
  type QuizExemptionsDTO,
  type QuizExemptionStudentDTO,
  type QuizSummaryDTO,
  type TeacherQuizDTO,
} from "@/lib/api/quiz";
import { useT } from "@/lib/i18n";
import {
  formatQuizTime,
  fromDatetimeLocal,
  toDatetimeLocal,
} from "@/lib/quiz-time";
import { cn } from "@/lib/utils";
import { useSession } from "../session-provider";
import { ErrorNotice } from "../ui";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { WorkspaceIcon } from "../workspace-icon";
import { QuizKey } from "./quiz-chrome";

export const TZ_TAG = (
  <span className="rounded-md border-2 border-border bg-white px-1.5 py-0.5 font-mono text-[11px] font-bold text-ink">
    UTC+8
  </span>
);

const STICKER =
  "inline-flex shrink-0 items-center gap-1.5 rounded-lg border-2 border-border px-2.5 py-1 font-body text-xs font-extrabold text-ink shadow-[2px_2px_0_#111]";

const TONE: Record<"lime" | "yellow" | "cyan", string> = {
  lime: "bg-[#BEF264]",
  yellow: "bg-[#FFE14D]",
  cyan: "bg-[#A5F3FC]",
};

export function QuizSticker({
  tone,
  tilt = true,
  testId,
  children,
}: {
  tone: "lime" | "yellow" | "cyan";
  tilt?: boolean;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(STICKER, TONE[tone], tilt ? "-rotate-1" : "")}
      data-testid={testId}
    >
      <WorkspaceIcon name="clock" size={14} stroke={2.6} />
      {children}
    </span>
  );
}

const HELP_BUTTON =
  "m-0 box-border grid size-[18px] flex-none cursor-help place-items-center rounded-full border-2 border-[#111] bg-[#FFE14D] p-0 font-body text-[10px] leading-none font-extrabold text-[#111] shadow-none";

export function QuizHelp({
  label,
  text,
  guide,
}: {
  label: string;
  text: string;
  guide: string;
}) {
  return (
    <button
      type="button"
      className={HELP_BUTTON}
      aria-label={label}
      data-ui-guide={guide}
      data-ui-guide-text={text}
      data-ui-guide-hover="true"
    >
      ?
    </button>
  );
}

export function TeacherScheduleStickers({
  startAt,
  endAt,
}: {
  startAt?: string | null;
  endAt?: string | null;
}) {
  const t = useT();
  return (
    <>
      {startAt ? (
        <QuizSticker tone="lime">
          {t("quizOpensAt", { time: formatQuizTime(startAt) })}
        </QuizSticker>
      ) : null}
      {endAt ? (
        <QuizSticker tone="yellow" tilt={false}>
          {t("quizClosesAt", { time: formatQuizTime(endAt) })}
        </QuizSticker>
      ) : null}
    </>
  );
}

export function TeacherExtendedSticker({ count }: { count?: number }) {
  const t = useT();
  if (!count) return null;
  return (
    <QuizSticker tone="cyan" testId="quiz-extended-badge">
      {t("quizExtendCount", { count })}
    </QuizSticker>
  );
}

export function StudentQuizStickers({
  quiz,
}: {
  quiz: {
    exempt_until?: string | null;
    scheduled_start_at?: string | null;
    scheduled_end_at?: string | null;
    taking_open?: boolean | null;
    can_take_now?: boolean | null;
  };
}) {
  const t = useT();
  const open = quiz.taking_open === true || quiz.can_take_now === true;
  return (
    <>
      {quiz.exempt_until ? (
        <QuizSticker tone="lime" testId="quiz-extended-badge">
          {t("quizExtendedUntil", { time: formatQuizTime(quiz.exempt_until) })}
        </QuizSticker>
      ) : null}
      {open && quiz.scheduled_end_at ? (
        <QuizSticker tone="yellow" tilt={false}>
          {t("quizClosesUntil", {
            time: formatQuizTime(quiz.scheduled_end_at),
          })}
        </QuizSticker>
      ) : null}
      {!open && quiz.scheduled_start_at ? (
        <QuizSticker tone="lime">
          {t("quizOpensUntil", {
            time: formatQuizTime(quiz.scheduled_start_at),
          })}
        </QuizSticker>
      ) : null}
    </>
  );
}

type OpenPanel = "extend" | "schedule" | null;

export function QuizTakingControls({
  courseId,
  quiz,
  busy: busyProp,
  onQuizUpdated,
  onError,
  trailing,
}: {
  courseId: string;
  quiz: QuizSummaryDTO;
  busy?: boolean;
  onQuizUpdated: (next: QuizSummaryDTO | TeacherQuizDTO) => void;
  onError?: (cause: unknown | null) => void;
  trailing?: ReactNode;
}) {
  const t = useT();
  const { api } = useSession();
  const quizApi = useMemo(() => new QuizApi(api), [api]);
  const [open, setOpen] = useState<OpenPanel>(null);
  const [busyAction, setBusyAction] = useState<"start" | "pause" | null>(null);
  const busy = Boolean(busyProp || busyAction);

  const onToggle = async (next: "start" | "pause") => {
    if (busy) return;
    setBusyAction(next);
    onError?.(null);
    try {
      const updated =
        next === "start"
          ? await quizApi.startTaking(courseId, quiz.id)
          : await quizApi.pauseTaking(courseId, quiz.id);
      onQuizUpdated(updated);
      setOpen(null);
    } catch (cause) {
      onError?.(cause);
    } finally {
      setBusyAction(null);
    }
  };

  const takingOpen = quiz.taking_open === true;
  const neverStarted = (quiz.taking_epoch ?? 0) === 0;

  const scheduleAnchor = useRef<HTMLSpanElement>(null);

  return (
    <>
      <div className="flex flex-wrap gap-2.5 max-[600px]:w-full">
        <span
          className="relative inline-flex min-w-0 shrink-0"
          ref={scheduleAnchor}
        >
          <span className="inline-flex max-w-full">
            {takingOpen ? (
              <QuizKey
                icon="pause"
                busy={busyAction === "pause"}
                disabled={busy}
                className="rounded-r-none"
                onClick={() => void onToggle("pause")}
              >
                {t("quizPauseEvaluation")}
              </QuizKey>
            ) : (
              <QuizKey
                icon="play"
                tone="primary"
                busy={busyAction === "start"}
                disabled={busy}
                className="rounded-r-none"
                onClick={() => void onToggle("start")}
              >
                {t("quizStartEvaluation")}
              </QuizKey>
            )}
            <QuizKey
              icon="clock"
              ariaLabel={t("quizSchedule")}
              testId="quiz-schedule"
              className="-ml-px rounded-l-none px-3 max-[600px]:flex-none max-[600px]:flex-row max-[600px]:px-3 max-[600px]:py-[7px]"
              disabled={busy}
              onClick={() =>
                setOpen((current) =>
                  current === "schedule" ? null : "schedule",
                )
              }
            >
              <span className="sr-only">{t("quizSchedule")}</span>
            </QuizKey>
          </span>
          {open === "schedule" ? (
            <SchedulePopover
              courseId={courseId}
              quiz={quiz}
              quizApi={quizApi}
              anchorRef={scheduleAnchor}
              onClose={() => setOpen(null)}
              onSaved={(updated) => {
                onQuizUpdated(updated);
                setOpen(null);
              }}
            />
          ) : null}
        </span>
        <ExtendKey
          disabled={busy}
          neverStarted={neverStarted}
          expanded={open === "extend"}
          onClick={() =>
            setOpen((current) => (current === "extend" ? null : "extend"))
          }
        />
        {trailing}
      </div>
      {open === "extend" && !neverStarted ? (
        <ExtendPanel
          courseId={courseId}
          quizId={quiz.id}
          quizApi={quizApi}
          onClose={() => setOpen(null)}
          onChanged={(count) =>
            onQuizUpdated({
              ...quiz,
              exemption_count: count,
            })
          }
        />
      ) : null}
    </>
  );
}

function ExtendKey({
  disabled,
  neverStarted,
  expanded,
  onClick,
}: {
  disabled?: boolean;
  neverStarted: boolean;
  expanded: boolean;
  onClick: MouseEventHandler<HTMLButtonElement>;
}) {
  const t = useT();
  const key = (
    <QuizKey
      icon="accounts"
      testId="quiz-extend"
      disabled={disabled || neverStarted}
      ariaLabel={t("quizExtendTime")}
      onClick={onClick}
    >
      {t("quizExtendTime")}
    </QuizKey>
  );
  if (!neverStarted) {
    return (
      <span className="inline-flex" aria-expanded={expanded}>
        {key}
      </span>
    );
  }
  return (
    <span
      className="inline-flex"
      data-ui-guide="quiz.extendDisabled"
      data-ui-guide-text={t("quizExtendNotStarted")}
      data-ui-guide-hover="true"
      title={t("quizExtendNotStarted")}
    >
      {key}
    </span>
  );
}

const CARD =
  "rounded-2xl border-[3px] border-border bg-white p-4 shadow-[6px_6px_0_#111]";

function SchedulePopover({
  courseId,
  quiz,
  quizApi,
  onClose,
  onSaved,
  anchorRef,
}: {
  courseId: string;
  quiz: QuizSummaryDTO;
  quizApi: QuizApi;
  onClose: () => void;
  onSaved: (quiz: TeacherQuizDTO) => void;
  anchorRef: RefObject<HTMLSpanElement | null>;
}) {
  const t = useT();
  const rootRef = useRef<HTMLDivElement>(null);
  const [start, setStart] = useState(toDatetimeLocal(quiz.scheduled_start_at));
  const [end, setEnd] = useState(toDatetimeLocal(quiz.scheduled_end_at));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [pos, setPos] = useState({ top: 0, left: 12, width: 400 });

  useLayoutEffect(() => {
    const update = () => {
      const rect = anchorRef.current?.getBoundingClientRect();
      const margin = 12;
      const width = Math.min(400, window.innerWidth - margin * 2);
      if (!rect) {
        setPos({ top: 80, left: margin, width });
        return;
      }
      const left = Math.max(
        margin,
        Math.min(rect.right - width, window.innerWidth - width - margin),
      );
      const cardH = rootRef.current?.offsetHeight ?? 360;
      const below = rect.bottom + 8;
      let top = below;
      if (below + cardH > window.innerHeight - margin) {
        top = Math.max(margin, rect.top - 8 - cardH);
        if (top + cardH > window.innerHeight - margin) {
          top = Math.max(margin, window.innerHeight - margin - cardH);
        }
      }
      setPos({ top, left, width });
    };
    update();
    const raf = requestAnimationFrame(update);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [anchorRef, start, end, error, busy]);

  useEffect(() => {
    const onDoc = (event: MouseEvent) => {
      const target = event.target as Node;
      if (rootRef.current?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [anchorRef, onClose]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const updated = await quizApi.putSchedule(courseId, quiz.id, {
        start_at: start ? fromDatetimeLocal(start) : null,
        end_at: end ? fromDatetimeLocal(end) : null,
      });
      onSaved(updated);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  };

  const card = (
    <div
      ref={rootRef}
      className="fixed z-[80]"
      style={{ top: pos.top, left: pos.left, width: pos.width }}
      role="dialog"
      aria-label={t("quizSchedule")}
    >
      <div
        className={`${CARD} max-h-[min(480px,calc(100vh-24px))] overflow-auto`}
      >
        <div className="mb-3 flex items-center gap-2">
          <h3 className="m-0 font-display text-xl font-extrabold text-ink">
            {t("quizSchedule")}
          </h3>
          <QuizHelp
            label={t("quizAboutSchedule")}
            text={t("quizScheduleHelp")}
            guide="quiz.scheduleHelp"
          />
        </div>
        {error ? <ErrorNotice error={error} /> : null}
        <div className="grid gap-3.5">
          <ScheduleField
            label={t("quizStartEvaluationAt")}
            value={start}
            tone="bg-[#ECFCCB]"
            disabled={busy}
            onChange={setStart}
          />
          <ScheduleField
            label={t("quizPauseEvaluationAt")}
            value={end}
            tone="bg-[#FFF3C4]"
            disabled={busy}
            onChange={setEnd}
          />
        </div>
        <div className="mt-3.5 flex flex-wrap gap-2.5">
          <Button
            className="min-h-11 font-extrabold"
            disabled={busy}
            onClick={() => void save()}
          >
            {t("quizSaveSchedule")}
          </Button>
          <Button
            variant="neutral"
            className="min-h-11 font-extrabold"
            disabled={busy}
            onClick={onClose}
          >
            {t("quizCancel")}
          </Button>
        </div>
      </div>
    </div>
  );
  return createPortal(card, document.body);
}

function ScheduleField({
  label,
  value,
  tone,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  tone: string;
  disabled?: boolean;
  onChange: (next: string) => void;
}) {
  const t = useT();
  const id = label.replace(/\s+/g, "-").toLowerCase();
  return (
    <div
      className={cn(
        "grid gap-2 rounded-xl border-[3px] border-border p-3 shadow-[3px_3px_0_#111]",
        tone,
      )}
    >
      <label htmlFor={id} className="font-body text-sm font-extrabold text-ink">
        {label}
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          id={id}
          type="datetime-local"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          className="min-w-[200px] flex-1 bg-white"
        />
        {TZ_TAG}
        <button
          type="button"
          aria-label={t("quizClearNamed", { label })}
          className="grid size-10 shrink-0 cursor-pointer place-items-center rounded-lg border-[3px] border-border bg-white"
          disabled={disabled || !value}
          onClick={() => onChange("")}
        >
          <WorkspaceIcon name="close" size={13} stroke={2.6} />
        </button>
      </div>
    </div>
  );
}

function ExtendPanel({
  courseId,
  quizId,
  quizApi,
  onClose,
  onChanged,
}: {
  courseId: string;
  quizId: string;
  quizApi: QuizApi;
  onClose: () => void;
  onChanged: (activeCount: number) => void;
}) {
  const t = useT();
  const [data, setData] = useState<QuizExemptionsDTO | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [deadline, setDeadline] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const next = await quizApi.listExemptions(courseId, quizId);
      setData(next);
    } catch (cause) {
      setError(cause);
    }
  }, [courseId, quizId, quizApi]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const students = data?.students ?? [];
  const exemptions = data?.exemptions ?? [];
  const rows = students.filter((student) => {
    const hay = `${student.display_name} ${student.username}`.toLowerCase();
    return hay.includes(query.trim().toLowerCase());
  });
  const n = picked.length;

  const toggle = (student: QuizExemptionStudentDTO) => {
    if (student.submitted) return;
    setPicked((current) =>
      current.includes(student.student_id)
        ? current.filter((id) => id !== student.student_id)
        : [...current, student.student_id],
    );
  };

  const grant = async () => {
    const at = fromDatetimeLocal(deadline);
    if (!at || n === 0) return;
    setBusy(true);
    setError(null);
    try {
      const next = await quizApi.putExemptions(courseId, quizId, {
        student_ids: picked,
        deadline_at: at,
      });
      setData(next);
      setPicked([]);
      onChanged(next.exemptions.filter((row) => row.active).length);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  };

  const removeOne = async (studentId: string) => {
    setBusy(true);
    setError(null);
    try {
      await quizApi.deleteExemption(courseId, quizId, studentId);
      const next = await quizApi.listExemptions(courseId, quizId);
      setData(next);
      onChanged(next.exemptions.filter((row) => row.active).length);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  };

  const removeAll = async () => {
    setBusy(true);
    setError(null);
    try {
      await quizApi.clearExemptions(courseId, quizId);
      const next = await quizApi.listExemptions(courseId, quizId);
      setData(next);
      onChanged(0);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  };

  const extendLabel =
    n === 0
      ? t("quizExtendNone")
      : n === 1
        ? t("quizExtendStudents", { n })
        : t("quizExtendStudentsPlural", { n });

  return (
    <div className="min-w-0 max-w-full basis-full border-t-[3px] border-dashed border-border px-1 pt-4">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="m-0 font-display text-xl font-extrabold text-ink">
          {t("quizExtendTime")}
        </h3>
        <QuizHelp
          label={t("quizAboutExtendTime")}
          text={t("quizExtendHelp")}
          guide="quiz.extendHelp"
        />
      </div>
      {error ? <ErrorNotice error={error} /> : null}
      <div className="grid gap-4 md:grid-cols-[1.2fr_1fr]">
        <div className="grid min-w-0 gap-2.5">
          <Input
            placeholder={t("quizSearchStudents")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label={t("quizSearchStudents")}
          />
          <ul className="m-0 grid max-h-[272px] list-none gap-1.5 overflow-auto rounded-xl border-[3px] border-border bg-white p-2">
            {rows.map((student) => {
              const on = picked.includes(student.student_id);
              return (
                <li key={student.student_id}>
                  <label
                    className={cn(
                      "flex items-center gap-2.5 rounded-lg px-2 py-1.5 font-body text-sm font-bold",
                      student.submitted
                        ? "cursor-not-allowed opacity-55"
                        : "cursor-pointer hover:bg-[#FFF3C4]",
                      on ? "bg-[#FFF3C4]" : "",
                    )}
                  >
                    <input
                      type="checkbox"
                      className="size-[18px] accent-[#FF4D8D]"
                      disabled={student.submitted || busy}
                      checked={on}
                      onChange={() => toggle(student)}
                    />
                    <span className="min-w-0 flex-1 truncate">
                      {student.display_name}{" "}
                      <span className="font-semibold text-arc-muted">
                        @{student.username}
                      </span>
                    </span>
                    {student.submitted ? (
                      <span className="inline-flex items-center rounded-full border-2 border-border bg-[#ECFCCB] px-2 py-0.5 text-[11px] font-extrabold">
                        {t("quizSubmitted")}
                      </span>
                    ) : null}
                  </label>
                </li>
              );
            })}
          </ul>
        </div>
        <div className="grid min-w-0 content-start gap-3.5">
          <label className="grid gap-1.5">
            <span className="font-body text-sm font-extrabold text-ink">
              {t("quizExtendUntil")}
            </span>
            <div className="flex items-center gap-2">
              <Input
                type="datetime-local"
                value={deadline}
                disabled={busy}
                onChange={(event) => setDeadline(event.target.value)}
                className="min-w-0 flex-1"
              />
              {TZ_TAG}
            </div>
          </label>
          <div className="grid gap-2">
            <span className="font-body text-sm font-extrabold text-ink">
              {t("quizCurrentlyExtended")}{" "}
              <span className="rounded-full border-2 border-border bg-white px-2 font-mono text-xs">
                {exemptions.length}
              </span>
            </span>
            {exemptions.length === 0 ? (
              <p className="m-0 font-body text-sm font-semibold text-ink">
                {t("quizNoOneExtended")}
              </p>
            ) : (
              <ul className="m-0 grid list-none gap-1.5 p-0">
                {exemptions.map((row) => (
                  <li
                    key={row.id}
                    className="flex items-center gap-2 rounded-lg border-2 border-border bg-[#ECFCCB] px-2.5 py-1.5 font-body text-sm font-bold"
                  >
                    <span className="min-w-0 flex-1 truncate">
                      {row.display_name}
                    </span>
                    <span className="shrink-0 text-xs font-semibold">
                      {t("quizUntilTime", {
                        time: formatQuizTime(row.deadline_at),
                      })}
                    </span>
                    <button
                      type="button"
                      aria-label={t("quizRemoveNamed", {
                        name: row.display_name,
                      })}
                      className="grid size-6 shrink-0 cursor-pointer place-items-center rounded-md border-2 border-border bg-white"
                      disabled={busy}
                      onClick={() => void removeOne(row.student_id)}
                    >
                      <WorkspaceIcon name="close" size={11} stroke={2.6} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {exemptions.length ? (
              <button
                type="button"
                className="w-fit cursor-pointer border-0 bg-transparent p-0 font-body text-xs font-extrabold text-ink underline"
                disabled={busy}
                onClick={() => void removeAll()}
              >
                {t("quizRemoveAll")}
              </button>
            ) : null}
          </div>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2.5">
        <Button
          className="min-h-11 font-extrabold"
          disabled={busy || n === 0 || !deadline}
          onClick={() => void grant()}
        >
          {extendLabel}
        </Button>
        <Button
          variant="neutral"
          className="min-h-11 font-extrabold"
          disabled={busy}
          onClick={onClose}
        >
          {t("quizCancel")}
        </Button>
      </div>
    </div>
  );
}
