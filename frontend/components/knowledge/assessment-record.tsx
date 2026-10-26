"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import type { OverviewResult } from "../../lib/api/platform";
import { cachedCall, requestCacheIdentity } from "../../lib/request-cache";
import { useT } from "../../lib/i18n";
import { useSession } from "../session-provider";
import { IconClose, IconDownload } from "../quiet-icons";
import { ASSESSMENT_COMPLETED_EVENT } from "../../lib/assessment-events";
import { ErrorNotice } from "../ui";

type Translate = ReturnType<typeof useT>;

/**
 * Whose attempts Record reads: a teacher reads the whole course, a student
 * only their own, which the server enforces from the session.
 */
export type RecordScope = "course" | "own";

/** One assessment Team and every attempt the course has made on it. */
export type RecordTeam = {
  name: string;
  attempts: OverviewResult[];
  students: number;
  latest: string;
};

// Bug (2026-10-17, #123): Record stayed blank on every open while the list
// loaded. The last list per course shows at once and refreshes behind it.
const lastAttempts = new Map<string, OverviewResult[]>();

type AttemptsApi = {
  myAssessmentAttempts: (courseId: string) => Promise<OverviewResult[]>;
  courseAssessmentAttempts: (courseId: string) => Promise<OverviewResult[]>;
};

/**
 * Record's read through the shared request cache (same endpoints), so a page
 * that knows Record will mount (Studyform) can start it early and Record
 * joins that read instead of sending its own after the page paints.
 */
export function assessmentAttemptsRead(
  api: AttemptsApi,
  identity: string | null,
  scope: RecordScope,
  courseId: string,
  refresh = false,
): Promise<OverviewResult[]> {
  return scope === "own"
    ? cachedCall(
        api,
        identity,
        "myAssessmentAttempts",
        [courseId],
        () => api.myAssessmentAttempts(courseId),
        { refresh },
      )
    : cachedCall(
        api,
        identity,
        "courseAssessmentAttempts",
        [courseId],
        () => api.courseAssessmentAttempts(courseId),
        { refresh },
      );
}

/**
 * Every formal attempt in the course, grouped by the assessment Team's name,
 * most recently active Team first. Attempts inside a Team read by student.
 * A student's Record reads only the student's own attempts.
 */
export function useAssessmentRecord(
  courseId: string,
  enabled: boolean,
  scope: RecordScope = "course",
) {
  const { api, identityGeneration, user } = useSession();
  const cacheIdentity = requestCacheIdentity(user?.id, identityGeneration);
  // Per signed-in user: report links are each teacher's own, answers each
  // student's own.
  const cacheKey = `${scope}:${user?.id ?? ""}:${courseId}`;
  const [attempts, setAttempts] = useState<OverviewResult[] | null>(
    () => lastAttempts.get(cacheKey) ?? null,
  );
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(
    async (refresh = false) => {
      if (!enabled || !courseId) return;
      setError(null);
      try {
        // Through the shared cache so Studyform's own load can warm it.
        const next = await assessmentAttemptsRead(
          api,
          cacheIdentity,
          scope,
          courseId,
          refresh,
        );
        lastAttempts.set(cacheKey, next);
        setAttempts(next);
      } catch (cause) {
        setError(cause);
      }
    },
    [api, cacheIdentity, cacheKey, courseId, enabled, scope],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  // A Team test finished in this tab (Chatform): read Record again.
  useEffect(() => {
    const onCompleted = () => void load();
    window.addEventListener(ASSESSMENT_COMPLETED_EVENT, onCompleted);
    return () =>
      window.removeEventListener(ASSESSMENT_COMPLETED_EVENT, onCompleted);
  }, [load]);

  const teams = useMemo<RecordTeam[]>(() => {
    const byName = new Map<string, OverviewResult[]>();
    for (const attempt of attempts ?? []) {
      const rows = byName.get(attempt.team_name) ?? [];
      rows.push(attempt);
      byName.set(attempt.team_name, rows);
    }
    return [...byName.entries()]
      .map(([name, rows]) => ({
        name,
        attempts: [...rows].sort(
          (left, right) =>
            (scope === "own"
              ? 0
              : left.student_name.localeCompare(right.student_name)) ||
            right.started_at.localeCompare(left.started_at),
        ),
        students: new Set(rows.map((row) => row.user_id)).size,
        latest: rows.reduce((latest, row) => {
          const at = row.ended_at ?? row.started_at;
          return at > latest ? at : latest;
        }, ""),
      }))
      .sort((left, right) => right.latest.localeCompare(left.latest));
  }, [attempts, scope]);

  return { teams, loaded: attempts !== null, error, reload: () => load(true) };
}

function useWhen() {
  return (value: string) =>
    new Date(value).toLocaleString("en", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
}

const CHIP = [
  "bg-[#FF4D8D]",
  "bg-[#A3E635]",
  "bg-[#67E8F9]",
  "bg-[#C4B5FD]",
  "bg-[#FFE14D]",
] as const;

/** Cream clipboard board (shared list + detail chrome). */
function ClipboardBoard({
  children,
  labelledBy,
}: {
  children: ReactNode;
  labelledBy: string;
}) {
  return (
    <section
      aria-labelledby={labelledBy}
      className="relative mx-auto w-full max-w-[1120px] rounded-lg border-[4px] border-black bg-[#F5E6C8] bg-[radial-gradient(#E9DFC4_1.4px,transparent_1.4px)] bg-[length:22px_22px] px-9 pb-10 pt-14 shadow-[10px_10px_0_#111] min-h-[740px] before:absolute before:left-1/2 before:top-[-18px] before:h-9 before:w-[120px] before:-translate-x-1/2 before:rounded-t-lg before:rounded-b-sm before:border-[3px] before:border-black before:bg-[#9CA3AF] before:shadow-[inset_0_-6px_0_#6B7280] before:content-['']"
    >
      <span
        aria-hidden="true"
        className="absolute left-1/2 top-1.5 z-[2] h-7 w-9 -translate-x-1/2 rounded border-[3px] border-black bg-[#E5E7EB]"
      />
      {children}
    </section>
  );
}

function ListChrome({ teacher, intro }: { teacher: boolean; intro: string }) {
  return (
    <div className="mb-5 flex items-start gap-3.5">
      <h2
        id="brainform-record-heading"
        data-ui-guide="brainform.record"
        data-ui-guide-text={intro}
        tabIndex={0}
        className="m-0 inline-block -rotate-[1.5deg] rounded-md border-[3px] border-black border-l-[10px] border-l-[#FACC15] bg-white px-[18px] py-1 text-[40px] font-extrabold leading-none shadow-[4px_4px_0_#111]"
      >
        Record
      </h2>
      <span
        aria-hidden="true"
        className="mt-2.5 h-5 w-16 rotate-6 border-2 border-black bg-[rgba(103,232,249,0.75)]"
      />
      <span
        aria-hidden="true"
        className={`ml-auto rounded-lg border-[3px] px-3.5 py-1.5 text-[13px] font-extrabold ${
          teacher
            ? "rotate-8 border-[#EF4444] text-[#EF4444]"
            : "-rotate-6 border-[#16A34A] text-[#16A34A]"
        } bg-white/70`}
      >
        {teacher ? "CLASS ROSTER" : "MY PROGRESS"}
      </span>
    </div>
  );
}

function XpRibbon({ label, width = "62%" }: { label: string; width?: string }) {
  return (
    <div
      aria-hidden="true"
      className="mt-5 flex items-center gap-3 rounded-[14px] border-[3px] border-black bg-black px-3.5 py-2.5 shadow-[4px_4px_0_#FF4D8D]"
    >
      <span className="shrink-0 text-[11px] font-extrabold uppercase tracking-wider text-[#FFE14D]">
        {label}
      </span>
      <span className="h-4 flex-1 overflow-hidden rounded-full border-2 border-white bg-[#333]">
        <i
          className="block h-full bg-gradient-to-r from-[#FFE14D] via-[#A3E635] to-[#67E8F9]"
          style={{ width }}
        />
      </span>
    </div>
  );
}

function Burst({ n = 5 }: { n?: number }) {
  const tones = [
    "bg-[#FF4D8D] -rotate-8",
    "bg-[#A3E635] rotate-6",
    "bg-[#67E8F9] -rotate-3",
    "bg-[#FFE14D] rotate-[10deg]",
    "bg-[#C4B5FD] -rotate-5",
  ];
  return (
    <div aria-hidden="true" className="mt-3.5 flex flex-wrap gap-2">
      {tones.slice(0, n).map((cls, i) => (
        <i
          key={i}
          className={`h-7 w-7 rounded-lg border-2 border-black shadow-[2px_2px_0_#111] ${cls}`}
        />
      ))}
    </div>
  );
}

function EmptyAlbum() {
  const t = useT();
  return (
    <>
      <div className="mt-2 grid grid-cols-3 gap-x-5 gap-y-6">
        <div className="grid min-h-[280px] place-items-center content-center gap-3.5 rounded-[14px] border-[3px] border-black bg-white p-[22px] text-center shadow-[6px_6px_0_#111]">
          <span
            aria-hidden="true"
            className="relative grid h-[88px] w-[88px] place-items-center rounded-2xl border-[3px] border-black bg-[#67E8F9] shadow-[4px_4px_0_#111]"
          >
            <span className="relative h-14 w-11 rounded border-[3px] border-black bg-[#FFF8E7] before:absolute before:left-1/2 before:top-[-8px] before:h-2.5 before:w-[22px] before:-translate-x-1/2 before:rounded-sm before:border-2 before:border-black before:bg-[#9CA3AF] before:content-['']" />
          </span>
          <p className="-rotate-2 inline-block rounded-xl border-[3px] border-black bg-[#FFE14D] px-4 py-2 text-xl font-extrabold shadow-[4px_4px_0_#111]">
            {t("overviewNoResults")}
          </p>
        </div>
        <div
          aria-hidden="true"
          className="grid min-h-[280px] place-items-center rounded-[14px] border-[3px] border-dashed border-[#B9AE90] bg-white/35 text-[42px] font-extrabold text-[#C4BAA0]"
        >
          +
        </div>
        <div
          aria-hidden="true"
          className="grid min-h-[280px] place-items-center rounded-[14px] border-[3px] border-dashed border-[#B9AE90] bg-white/35 text-[42px] font-extrabold text-[#C4BAA0]"
        >
          +
        </div>
      </div>
      <div aria-hidden="true" className="mt-[22px] flex flex-wrap gap-2.5">
        <i className="inline-block h-[22px] w-14 -rotate-3 rounded-lg border-2 border-black bg-[#C4B5FD] shadow-[2px_2px_0_#111]" />
        <i className="inline-block h-[22px] w-14 rotate-4 rounded-lg border-2 border-black bg-[#67E8F9] shadow-[2px_2px_0_#111]" />
        <i className="inline-block h-[22px] w-14 -rotate-1 rounded-lg border-2 border-black bg-[#FBCFE8] shadow-[2px_2px_0_#111]" />
        <i className="inline-block h-[22px] w-14 rotate-5 rounded-lg border-2 border-black bg-[#FFE14D] shadow-[2px_2px_0_#111]" />
      </div>
    </>
  );
}

const cardShell =
  "relative flex w-full flex-wrap items-center gap-3.5 rounded-[14px] border-[3px] border-black bg-white px-[18px] py-4 text-left font-inherit text-inherit shadow-[6px_6px_0_#111] [transform:none]";

function tonePill(tone: string): string {
  if (tone === "high") return "bg-[#A3E635] text-black";
  if (tone === "mid") return "bg-[#FDE68A] text-black";
  if (tone === "low") return "bg-[#FCA5A5] text-black";
  if (tone === "warn") return "bg-[#FDE68A] text-black";
  return "bg-[#E5E7EB] text-[#555]";
}

/** The Brainform column: one row per assessment Team. */
export function RecordSection({
  teams,
  loaded,
  error,
  onRetry,
  onOpen,
  scope = "course",
  guideText,
}: {
  scope?: RecordScope;
  teams: RecordTeam[];
  loaded: boolean;
  error: unknown;
  onRetry: () => void;
  onOpen: (team: string) => void;
  /** Optional override for data-ui-guide-text (keeps existing copy). */
  guideText?: string;
}) {
  const t = useT();
  const when = useWhen();
  const teacher = scope !== "own";
  const intro =
    guideText ??
    t(scope === "own" ? "recordOwnIntro" : "recordIntro");

  return (
    <ClipboardBoard labelledBy="brainform-record-heading">
      <ListChrome teacher={teacher} intro={intro} />
      {error ? (
        <ErrorNotice inline error={error} onRetry={onRetry} />
      ) : !loaded ? (
        <ul className="m-0 flex list-none flex-col gap-4 p-0" aria-busy="true" aria-label={t("loading")}>
          {[0, 1, 2].map((index) => (
            <li key={index} className={`${cardShell} animate-pulse`}>
              <span className="h-3.5 w-3/5 rounded bg-[#EBE5DA]" />
              <span className="ml-auto h-[38px] w-[38px] rounded-full bg-[#EBE5DA]" />
            </li>
          ))}
        </ul>
      ) : teams.length ? (
        <>
          <ul className="m-0 flex list-none flex-col gap-4 p-0">
            {teams.map((team, index) => (
              <li key={team.name}>
                <button
                  type="button"
                  className={cardShell}
                  aria-label={t(
                    scope === "own" ? "recordOwnOpenNamed" : "recordOpenNamed",
                    { name: team.name },
                  )}
                  onClick={() => onOpen(team.name)}
                >
                  <span
                    aria-hidden="true"
                    className="absolute right-7 top-[-8px] h-3.5 w-12 rotate-8 border-2 border-black bg-[rgba(103,232,249,0.85)]"
                  />
                  <span
                    aria-hidden="true"
                    className={`absolute left-[52px] top-[-10px] h-[22px] w-[22px] rounded-full border-2 border-black shadow-[2px_2px_0_#111] ${CHIP[index % CHIP.length]}`}
                  />
                  <span
                    aria-hidden="true"
                    className="w-7 shrink-0 font-mono text-sm font-extrabold text-[#9CA3AF]"
                  >
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col gap-1 text-left">
                    <span className="text-[17px] font-extrabold">{team.name}</span>
                    <span className="text-xs font-medium text-[#555]">
                      {scope === "own"
                        ? t("recordOwnMeta", { attempts: team.attempts.length })
                        : t("recordTeamMeta", {
                            students: team.students,
                            attempts: team.attempts.length,
                          })}
                      {team.latest ? ` · ${when(team.latest)}` : ""}
                    </span>
                  </span>
                  {scope === "own" ? (
                    <span
                      aria-hidden="true"
                      className="shrink-0 rounded-full border-2 border-black bg-[#E5E7EB] px-3 py-1 text-xs font-extrabold text-[#555]"
                    >
                      progress
                    </span>
                  ) : (
                    <ScoreRing ratio={averageRatio(team.attempts)} />
                  )}
                </button>
              </li>
            ))}
          </ul>
          {/* Filled: XP + burst only — no dashed album slots. */}
          <XpRibbon label="XP" />
          <Burst />
        </>
      ) : (
        <EmptyAlbum />
      )}
    </ClipboardBoard>
  );
}

/** The opened Team: a short summary, then each student's attempt. */
export function RecordDetail({
  team,
  scope = "course",
  onDelete,
}: {
  team: RecordTeam | undefined;
  scope?: RecordScope;
  /** A course teacher's delete; the server only hides the attempt. */
  onDelete?: (attempt: OverviewResult) => Promise<void>;
}) {
  const own = scope === "own";
  const t = useT();
  const when = useWhen();
  const [open, setOpen] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<unknown>(null);

  async function remove(attempt: OverviewResult) {
    if (!onDelete || deleting || !window.confirm(t("recordDeleteConfirm")))
      return;
    setDeleting(attempt.attempt_id);
    setDeleteError(null);
    try {
      await onDelete(attempt);
    } catch (cause) {
      setDeleteError(cause);
    } finally {
      setDeleting(null);
    }
  }
  if (!team) {
    return (
      <ClipboardBoard labelledBy="brainform-record-team">
        <p className="m-0 text-center text-base font-bold text-[#555]">
          {t("overviewNoResults")}
        </p>
      </ClipboardBoard>
    );
  }
  const completed = team.attempts.filter(
    (attempt) => attempt.status === "completed",
  ).length;
  const average = averageRatio(team.attempts);
  return (
    <ClipboardBoard labelledBy="brainform-record-team">
      <p className="mb-1 text-[11px] font-extrabold uppercase tracking-[1.4px] text-[#0E7490]">
        Record
      </p>
      <h2
        id="brainform-record-team"
        className="mb-4 mt-0 text-[34px] font-extrabold leading-none"
      >
        {team.name}
      </h2>

      <dl className="mb-[18px] flex flex-wrap gap-3">
        {own ? (
          <div className="min-w-[120px] rounded-lg border-[3px] border-black bg-white px-3.5 py-2.5 shadow-[3px_3px_0_#111]">
            <dt className="mb-0.5 text-[10px] font-extrabold tracking-wide text-[#666]">
              {t("recordAttempts")}
            </dt>
            <dd className="m-0 text-2xl font-extrabold">{team.attempts.length}</dd>
          </div>
        ) : (
          <div className="min-w-[120px] rounded-lg border-[3px] border-black bg-white px-3.5 py-2.5 shadow-[3px_3px_0_#111]">
            <dt className="mb-0.5 text-[10px] font-extrabold tracking-wide text-[#666]">
              {t("recordStudents")}
            </dt>
            <dd className="m-0 text-2xl font-extrabold">{team.students}</dd>
          </div>
        )}
        <div className="min-w-[120px] rounded-lg border-[3px] border-black bg-white px-3.5 py-2.5 shadow-[3px_3px_0_#111]">
          <dt className="mb-0.5 text-[10px] font-extrabold tracking-wide text-[#666]">
            {t("recordCompleted")}
          </dt>
          <dd className="m-0 text-2xl font-extrabold">
            {completed}
            <small className="text-sm font-bold text-[#555]">
              {" "}
              / {team.attempts.length}
            </small>
          </dd>
        </div>
        {own ? null : (
          <div className="min-w-[120px] rounded-lg border-[3px] border-black bg-white px-3.5 py-2.5 shadow-[3px_3px_0_#111]">
            <dt className="mb-0.5 text-[10px] font-extrabold tracking-wide text-[#666]">
              {t("recordAverage")}
            </dt>
            <dd className="m-0 text-2xl font-extrabold">
              {average === null ? "—" : `${Math.round(average * 100)}%`}
            </dd>
          </div>
        )}
      </dl>

      {deleteError ? <ErrorNotice inline error={deleteError} /> : null}
      <ul className="m-0 flex list-none flex-col gap-4 p-0">
        {team.attempts.map((attempt, index) => {
          const key = attempt.attempt_id;
          const ratio = attemptRatio(attempt);
          const version = attempt.test_name.startsWith(`${team.name} · `)
            ? attempt.test_name.slice(team.name.length + 3)
            : attempt.test_name;
          const pillTone = own ? "muted" : tone(attempt, ratio);
          return (
            <li key={key} className={cardShell}>
              <span
                aria-hidden="true"
                className="absolute right-7 top-[-8px] h-3.5 w-12 rotate-8 border-2 border-black bg-[rgba(103,232,249,0.85)]"
              />
              <span
                aria-hidden="true"
                className={`absolute left-[52px] top-[-10px] h-[22px] w-[22px] rounded-full border-2 border-black shadow-[2px_2px_0_#111] ${CHIP[index % CHIP.length]}`}
              />
              <span
                aria-hidden="true"
                className="w-7 shrink-0 font-mono text-sm font-extrabold text-[#9CA3AF]"
              >
                {String(index + 1).padStart(2, "0")}
              </span>
              <button
                type="button"
                className="flex min-w-0 flex-1 cursor-pointer items-center gap-3.5 border-0 bg-transparent p-0 text-left font-inherit text-inherit"
                aria-expanded={open === key}
                onClick={() =>
                  setOpen((current) => (current === key ? null : key))
                }
              >
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="text-[17px] font-extrabold">
                    {own ? version : attempt.student_name}
                  </span>
                  <span className="text-xs font-medium text-[#555]">
                    {(own
                      ? [when(attempt.started_at)]
                      : [
                          attempt.group_name,
                          version,
                          // Owner request (2026-10-18): a revoked version's
                          // attempts stay in Record, labelled as such.
                          attempt.publication_state === "revoked"
                            ? t("recordRevokedVersion")
                            : null,
                          when(attempt.started_at),
                        ]
                    )
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
                <span
                  className={`shrink-0 rounded-full border-2 border-black px-3 py-1 text-xs font-extrabold ${tonePill(pillTone)}`}
                >
                  {own ? progress(attempt, t) : score(attempt, t)}
                </span>
              </button>
              {!own && (attempt.report_download_path || onDelete) ? (
                <div className="flex shrink-0 gap-2">
                  {attempt.report_download_path ? (
                    <a
                      className="inline-flex h-9 items-center gap-1 rounded-lg border-2 border-black bg-[#67E8F9] px-2.5 text-xs font-extrabold text-black no-underline shadow-[2px_2px_0_#111]"
                      href={attempt.report_download_path}
                      download
                      // The report covers the whole test, not this attempt.
                      aria-label={t("recordReportFor", {
                        name: attempt.test_name,
                      })}
                    >
                      <IconDownload />
                      {t("overviewReport")}
                    </a>
                  ) : null}
                  {onDelete ? (
                    <button
                      type="button"
                      className="inline-flex h-9 items-center justify-center rounded-lg border-2 border-black bg-[#EF4444] px-2.5 text-white shadow-[2px_2px_0_#111]"
                      aria-label={t("recordDeleteNamed", {
                        name: attempt.student_name,
                      })}
                      disabled={deleting === key}
                      onClick={() => void remove(attempt)}
                    >
                      <IconClose />
                    </button>
                  ) : null}
                </div>
              ) : null}
              {open === key ? (
                <div className="basis-full pt-3">
                  <AnswerSheet result={attempt} own={own} />
                  {!own && attempt.conversation_id ? (
                    <p className="mt-1.5 text-xs text-[#555]">
                      {t("overviewConversation")}{" "}
                      <code>{attempt.conversation_id}</code>
                    </p>
                  ) : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
      {/* Detail: RUN/burst only — no dashed slots. Student cards stay flat 0°. */}
      {own ? <XpRibbon label="RUN" width="50%" /> : null}
      <Burst n={own ? 3 : 4} />
    </ClipboardBoard>
  );
}

function attemptRatio(attempt: OverviewResult): number | null {
  if (attempt.status !== "completed") return null;
  const awarded = attempt.points_awarded;
  const total = attempt.points_total;
  if (awarded === null || awarded === undefined || !total) return null;
  return Math.max(0, Math.min(1, awarded / total));
}

function averageRatio(attempts: OverviewResult[]): number | null {
  const ratios = attempts
    .map(attemptRatio)
    .filter((ratio): ratio is number => ratio !== null);
  if (!ratios.length) return null;
  return ratios.reduce((sum, ratio) => sum + ratio, 0) / ratios.length;
}

function tone(attempt: OverviewResult, ratio: number | null): string {
  if (
    attempt.phase === "summary_not_saved" ||
    attempt.phase === "scoring_not_saved"
  )
    return "warn";
  if (ratio === null) return "muted";
  if (ratio >= 0.8) return "high";
  if (ratio >= 0.6) return "mid";
  return "low";
}

/** The Team's average completed score, drawn as a small ring. */
function ScoreRing({ ratio }: { ratio: number | null }) {
  if (ratio === null) return null;
  const percent = Math.round(ratio * 100);
  return (
    <span
      className="grid h-12 w-12 shrink-0 place-items-center rounded-full border-[3px] border-black shadow-[3px_3px_0_#111]"
      style={
        {
          background: `conic-gradient(#FF4D8D ${percent}%, #fff 0)`,
        } as CSSProperties
      }
      aria-hidden="true"
    >
      <span className="grid h-8 w-8 place-items-center rounded-full border-2 border-black bg-white font-mono text-xs font-extrabold">
        {percent}
      </span>
    </span>
  );
}

function score(result: OverviewResult, t: Translate): string {
  if (result.phase === "summary_not_saved") return t("overviewSummaryNotSaved");
  if (result.phase === "scoring_not_saved") return t("overviewScoringNotSaved");
  if (result.status === "in_progress") return t("recordUnfinished");
  if (result.status === "paused") return t("overviewPaused");
  const awarded = result.points_awarded;
  const total = result.points_total;
  if (awarded === null || awarded === undefined) return t("overviewNoScore");
  return total ? `${awarded} / ${total}` : `${awarded}`;
}

/** A student's own attempt: where it stands, never a score. */
function progress(result: OverviewResult, t: Translate): string {
  if (result.status === "completed") return t("recordCompleted");
  if (result.status === "paused") return t("overviewPaused");
  return t("overviewInProgress");
}

function AnswerSheet({
  result,
  own = false,
}: {
  result: OverviewResult;
  own?: boolean;
}) {
  const t = useT();
  return (
    <div className="my-1 overflow-x-auto rounded-[10px] border border-[#EBE5DF] bg-[#FFFDF8]">
      <table className="w-full min-w-[520px] border-collapse text-xs">
        <thead>
          <tr>
            <th scope="col" className="bg-[#F7F2EA] px-2.5 py-2 text-left font-semibold text-[#625E59]">
              #
            </th>
            <th scope="col" className="bg-[#F7F2EA] px-2.5 py-2 text-left font-semibold text-[#625E59]">
              {t("overviewQuestion")}
            </th>
            <th scope="col" className="bg-[#F7F2EA] px-2.5 py-2 text-left font-semibold text-[#625E59]">
              {t("overviewAnswer")}
            </th>
            {own ? null : (
              <>
                <th scope="col" className="bg-[#F7F2EA] px-2.5 py-2 text-left font-semibold text-[#625E59]">
                  {t("overviewPoints")}
                </th>
                <th scope="col" className="bg-[#F7F2EA] px-2.5 py-2 text-left font-semibold text-[#625E59]">
                  {t("overviewFeedback")}
                </th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {(result.questions ?? []).map((question) => (
            <tr key={question.number}>
              <td className="w-[2ch] border-b border-[#EBE5DF] px-2.5 py-2 align-top text-[#625E59]">
                {question.number}
              </td>
              <td className="overflow-wrap-anywhere border-b border-[#EBE5DF] px-2.5 py-2 align-top">
                {question.prompt}
              </td>
              <td className="overflow-wrap-anywhere border-b border-[#EBE5DF] px-2.5 py-2 align-top">
                {question.answers?.length
                  ? question.answers.join(" / ")
                  : question.skipped
                    ? t("overviewSkipped")
                    : t("overviewNotAnswered")}
              </td>
              {own ? null : (
                <>
                  <td className="border-b border-[#EBE5DF] px-2.5 py-2 align-top">
                    {question.points_awarded === null ||
                    question.points_awarded === undefined
                      ? "—"
                      : question.points_total
                        ? `${question.points_awarded} / ${question.points_total}`
                        : question.points_awarded}
                  </td>
                  <td className="border-b border-[#EBE5DF] px-2.5 py-2 align-top">
                    {question.feedback}
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
