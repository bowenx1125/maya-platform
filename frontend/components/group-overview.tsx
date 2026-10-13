"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type {
  GroupOverview as GroupOverviewData,
  OverviewEvent,
  OverviewResult,
} from "../lib/api/platform";
import styles from "./knowledge/brainform-workspace.module.css";
import overview from "./group-overview.module.css";
import { useLocale, useT } from "./locale";
import { useSession } from "./session-provider";
import { ModuleCard, ModuleGrid, ModuleList } from "./studyform-layout";
import { ErrorNotice } from "./ui";
import { UserAvatar } from "./user-avatar";

/**
 * What a group is doing, for a teacher who entered it from Accounts: who is
 * in it and what each made, their test results with every answer, and what
 * happened lately. Everything here is read-only.
 */
export function GroupOverview({ groupId }: { groupId: string }) {
  const t = useT();
  const { locale } = useLocale();
  const { api } = useSession();
  const [data, setData] = useState<GroupOverviewData | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await api.groupOverview(groupId));
    } catch (cause) {
      setError(cause);
    }
  }, [api, groupId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const when = (value: string) =>
    new Date(value).toLocaleString(locale === "zh" ? "zh-CN" : "en", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  const toggle = (key: string) =>
    setOpen((current) => (current === key ? null : key));

  if (error)
    return <ErrorNotice inline error={error} onRetry={() => void load()} />;
  if (!data) return null;
  const members = data.members ?? [];
  const results = data.results ?? [];
  const activity = data.activity ?? [];

  return (
    <ModuleGrid>
      <ModuleCard
        title={t("overviewMembers")}
        count={members.length}
        labelledBy="group-overview-members"
        empty={members.length ? undefined : t("overviewNoMembers")}
      >
        {members.length ? (
          <ModuleList>
            {members.map((member) => {
              const key = `member:${member.user_id}`;
              const work = [
                ...(member.agents ?? []).map((agent) => ({
                  ...agent,
                  href: `/student/agents/${agent.id}`,
                })),
                ...(member.teams ?? []).map((team) => ({
                  ...team,
                  href: `/student/groups/${groupId}?mode=team-edit&team_id=${encodeURIComponent(team.id)}`,
                })),
              ];
              return (
                <li className={styles.row} key={member.user_id}>
                  <button
                    type="button"
                    className={`${styles.rowHit} ${overview.person}`}
                    aria-expanded={open === key}
                    onClick={() => toggle(key)}
                  >
                    <UserAvatar
                      avatar={member.avatar}
                      name={member.display_name}
                      userId={member.user_id}
                      size="sm"
                    />
                    <span className={styles.rowCopy}>
                      <span className={styles.staticTitle}>
                        {member.display_name}
                      </span>
                      <span className={styles.rowMeta}>
                        {t("overviewWorkCounts", {
                          agents: member.agents?.length ?? 0,
                          teams: member.teams?.length ?? 0,
                          rag: member.rag_count ?? 0,
                          voices: member.voice_count ?? 0,
                        })}
                      </span>
                    </span>
                  </button>
                  {open === key ? (
                    <div className={styles.rowExtra}>
                      {work.length ? (
                        <ul className={overview.work}>
                          {work.map((item) => (
                            <li key={item.id}>
                              <Link href={item.href}>{item.name}</Link>
                              <small>
                                {t(
                                  item.visibility === "public"
                                    ? "publicOption"
                                    : "privateOption",
                                )}
                              </small>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className={styles.rowMeta}>{t("overviewNoWork")}</p>
                      )}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ModuleList>
        ) : undefined}
      </ModuleCard>

      <ModuleCard
        title={t("overviewResults")}
        count={results.length}
        labelledBy="group-overview-results"
        empty={results.length ? undefined : t("overviewNoResults")}
      >
        {results.length ? (
          <ModuleList>
            {results.map((result) => {
              const key = `result:${result.attempt_id}`;
              return (
                <li className={styles.row} key={result.attempt_id}>
                  <button
                    type="button"
                    className={styles.rowHit}
                    aria-expanded={open === key}
                    onClick={() => toggle(key)}
                  >
                    <span className={styles.staticTitle}>
                      {result.student_name} · {result.team_name}
                    </span>
                    <span className={styles.rowMeta}>
                      {score(result, t)} · {when(result.started_at)}
                    </span>
                  </button>
                  {result.report_download_path ? (
                    <div className={styles.actions}>
                      <a
                        className={overview.report}
                        href={result.report_download_path}
                        download
                        aria-label={t("overviewReportFor", {
                          name: result.team_name,
                        })}
                      >
                        {t("overviewReport")}
                      </a>
                    </div>
                  ) : null}
                  {open === key ? (
                    <div className={styles.rowExtra}>
                      <AnswerSheet result={result} />
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ModuleList>
        ) : undefined}
      </ModuleCard>

      <ModuleCard
        title={t("overviewActivity")}
        labelledBy="group-overview-activity"
        empty={activity.length ? undefined : t("overviewNoActivity")}
      >
        {activity.length ? (
          <ModuleList>
            {activity.map((event, index) => (
              <li
                className={styles.row}
                key={`${event.kind}:${event.at}:${index}`}
              >
                <span className={styles.rowCopy}>
                  <span className={overview.event}>
                    <strong>{event.display_name}</strong> {eventText(event, t)}
                  </span>
                  <span className={styles.rowMeta}>{when(event.at)}</span>
                </span>
              </li>
            ))}
          </ModuleList>
        ) : undefined}
      </ModuleCard>
    </ModuleGrid>
  );
}

type Translate = ReturnType<typeof useT>;

function score(result: OverviewResult, t: Translate): string {
  if (result.status === "in_progress") return t("overviewInProgress");
  if (result.status === "paused") return t("overviewPaused");
  const awarded = result.points_awarded;
  const total = result.points_total;
  if (awarded === null || awarded === undefined) return t("overviewNoScore");
  return total ? `${awarded} / ${total}` : `${awarded}`;
}

function eventText(event: OverviewEvent, t: Translate): string {
  const values = { title: event.title };
  switch (event.kind) {
    case "agent_created":
      return t("overviewAgentCreated", values);
    case "agent_published":
      return t("overviewAgentPublished", values);
    case "team_created":
      return t("overviewTeamCreated", values);
    case "rag_added":
      return t("overviewRagAdded", values);
    case "voice_added":
      return t("overviewVoiceAdded", values);
    case "test_completed":
      return t("overviewTestCompleted", values);
  }
}

function AnswerSheet({ result }: { result: OverviewResult }) {
  const t = useT();
  return (
    <div className={overview.sheet}>
      <table>
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">{t("overviewQuestion")}</th>
            <th scope="col">{t("overviewAnswer")}</th>
            <th scope="col">{t("overviewPoints")}</th>
            <th scope="col">{t("overviewFeedback")}</th>
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
              <td>
                {question.points_awarded === null ||
                question.points_awarded === undefined
                  ? "—"
                  : question.points_total
                    ? `${question.points_awarded} / ${question.points_total}`
                    : question.points_awarded}
              </td>
              <td>{question.feedback}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
