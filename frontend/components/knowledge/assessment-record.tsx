"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
} from "react";

import type { OverviewResult } from "../../lib/api/platform";
import { cachedCall, requestCacheIdentity } from "../../lib/request-cache";
import { useLocale, useT } from "../locale";
import { useSession } from "../session-provider";
import { IconClose } from "../quiet-icons";
import { ErrorNotice } from "../ui";
import styles from "./brainform-workspace.module.css";
import record from "./assessment-record.module.css";

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
  const { locale } = useLocale();
  return (value: string) =>
    new Date(value).toLocaleString(locale === "zh" ? "zh-CN" : "en", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
}

/** The Brainform column: one row per assessment Team. */
export function RecordSection({
  teams,
  loaded,
  error,
  onRetry,
  onOpen,
  scope = "course",
}: {
  scope?: RecordScope;
  teams: RecordTeam[];
  loaded: boolean;
  error: unknown;
  onRetry: () => void;
  onOpen: (team: string) => void;
}) {
  const t = useT();
  const when = useWhen();
  return (
    <section
      className={styles.section}
      aria-labelledby="brainform-record-heading"
    >
      <div className={styles.sectionHeading}>
        <div>
          <h2
            id="brainform-record-heading"
            data-ui-guide="brainform.record"
            data-ui-guide-text={t(
              scope === "own" ? "recordOwnIntro" : "recordIntro",
            )}
            tabIndex={0}
          >
            Record
          </h2>
        </div>
        <span className={styles.count}>{teams.length}</span>
      </div>
      {error ? (
        <ErrorNotice inline error={error} onRetry={onRetry} />
      ) : !loaded ? (
        <ul className={styles.list} aria-busy="true" aria-label={t("loading")}>
          {[0, 1, 2].map((index) => (
            <li className={`${styles.row} ${record.skeletonRow}`} key={index}>
              <span className={record.skeletonLine} />
              <span className={record.skeletonRing} />
            </li>
          ))}
        </ul>
      ) : teams.length ? (
        <ul className={styles.list}>
          {teams.map((team) => (
            <li className={styles.row} key={team.name}>
              <button
                type="button"
                className={`${styles.rowHit} ${record.teamRow}`}
                aria-label={t(
                  scope === "own" ? "recordOwnOpenNamed" : "recordOpenNamed",
                  { name: team.name },
                )}
                onClick={() => onOpen(team.name)}
              >
                <span className={styles.rowCopy}>
                  <span className={styles.staticTitle}>{team.name}</span>
                  <span className={styles.rowMeta}>
                    {scope === "own"
                      ? t("recordOwnMeta", { attempts: team.attempts.length })
                      : t("recordTeamMeta", {
                          students: team.students,
                          attempts: team.attempts.length,
                        })}
                    {team.latest ? ` · ${when(team.latest)}` : ""}
                  </span>
                </span>
                {scope === "own" ? null : (
                  <ScoreRing ratio={averageRatio(team.attempts)} />
                )}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.empty}>{t("overviewNoResults")}</p>
      )}
    </section>
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
      <section className={styles.editorPanel}>
        <p className={styles.empty}>{t("overviewNoResults")}</p>
      </section>
    );
  }
  const completed = team.attempts.filter(
    (attempt) => attempt.status === "completed",
  ).length;
  const average = averageRatio(team.attempts);
  return (
    <section
      className={styles.editorPanel}
      aria-labelledby="brainform-record-team"
    >
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.eyebrow}>Record</p>
          <h2 id="brainform-record-team">{team.name}</h2>
        </div>
      </div>

      <dl className={record.stats}>
        {own ? (
          <div>
            <dt>{t("recordAttempts")}</dt>
            <dd>{team.attempts.length}</dd>
          </div>
        ) : (
          <div>
            <dt>{t("recordStudents")}</dt>
            <dd>{team.students}</dd>
          </div>
        )}
        <div>
          <dt>{t("recordCompleted")}</dt>
          <dd>
            {completed}
            <small> / {team.attempts.length}</small>
          </dd>
        </div>
        {own ? null : (
          <div>
            <dt>{t("recordAverage")}</dt>
            <dd>{average === null ? "—" : `${Math.round(average * 100)}%`}</dd>
          </div>
        )}
      </dl>

      {deleteError ? <ErrorNotice inline error={deleteError} /> : null}
      <ul className={styles.list}>
        {team.attempts.map((attempt) => {
          const key = attempt.attempt_id;
          const ratio = attemptRatio(attempt);
          const version = attempt.test_name.startsWith(`${team.name} · `)
            ? attempt.test_name.slice(team.name.length + 3)
            : attempt.test_name;
          return (
            <li className={styles.row} key={key}>
              <button
                type="button"
                className={`${styles.rowHit} ${record.attemptRow}`}
                aria-expanded={open === key}
                onClick={() =>
                  setOpen((current) => (current === key ? null : key))
                }
              >
                <span className={styles.rowCopy}>
                  <span className={styles.staticTitle}>
                    {own ? version : attempt.student_name}
                  </span>
                  <span className={styles.rowMeta}>
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
                  className={record.score}
                  data-tone={own ? "muted" : tone(attempt, ratio)}
                >
                  {own ? progress(attempt, t) : score(attempt, t)}
                </span>
              </button>
              {!own && (attempt.report_download_path || onDelete) ? (
                <div className={styles.actions}>
                  {attempt.report_download_path ? (
                    <a
                      className={record.report}
                      href={attempt.report_download_path}
                      download
                      // The report covers the whole test, not this attempt.
                      aria-label={t("recordReportFor", {
                        name: attempt.test_name,
                      })}
                    >
                      {t("overviewReport")}
                    </a>
                  ) : null}
                  {onDelete ? (
                    <button
                      type="button"
                      className={styles.iconButton}
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
                <div className={styles.rowExtra}>
                  <AnswerSheet result={attempt} own={own} />
                  {!own && attempt.conversation_id ? (
                    <p className={`${styles.rowMeta} ${record.conversation}`}>
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
    </section>
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
      className={record.ring}
      style={{ "--ratio": `${percent}%` } as CSSProperties}
      aria-hidden="true"
    >
      <span>{percent}</span>
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
    <div className={record.sheet}>
      <table>
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">{t("overviewQuestion")}</th>
            <th scope="col">{t("overviewAnswer")}</th>
            {own ? null : (
              <>
                <th scope="col">{t("overviewPoints")}</th>
                <th scope="col">{t("overviewFeedback")}</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {(result.questions ?? []).map((question) => (
            <tr key={question.number}>
              <td>{question.number}</td>
              <td>{question.prompt}</td>
              <td>
                {question.answers?.length
                  ? question.answers.join(" / ")
                  : question.skipped
                    ? t("overviewSkipped")
                    : t("overviewNotAnswered")}
              </td>
              {own ? null : (
                <>
                  <td>
                    {question.points_awarded === null ||
                    question.points_awarded === undefined
                      ? "—"
                      : question.points_total
                        ? `${question.points_awarded} / ${question.points_total}`
                        : question.points_awarded}
                  </td>
                  <td>{question.feedback}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
