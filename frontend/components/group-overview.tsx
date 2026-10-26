"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type {
  GroupOverview as GroupOverviewData,
  OverviewEvent,
} from "../lib/api/platform";
import styles from "./knowledge/brainform-workspace.module.css";
import { useT } from "../lib/i18n";
import { useSession } from "./session-provider";
import { ModuleCard, ModuleGrid, ModuleList } from "./studyform-layout";
import { ErrorNotice } from "./ui";
import { UserAvatar } from "./user-avatar";

/**
 * What a group is doing, for a course teacher: who is in it and what each
 * made and what happened lately. Test results live in the teacher's
 * Brainform Record. Private work is present only after Enter. Everything
 * here is read-only.
 */
export function GroupOverview({ groupId }: { groupId: string }) {
  const t = useT();
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
    new Date(value).toLocaleString("en", {
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
                    className={`${styles.rowHit} flex items-center gap-2.5`}
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
                        <ul className="my-0.5 mb-1.5 grid list-none gap-1.5 p-0 pl-[42px]">
                          {work.map((item) => (
                            <li key={item.id} className="flex min-w-0 items-baseline gap-2">
                              <Link className="font-semibold text-(--ink,#292820) [overflow-wrap:anywhere]" href={item.href}>{item.name}</Link>
                              <small className="text-[0.75rem] text-[#625e59]">
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
                  <span className="leading-[1.4] text-(--ink,#292820) [overflow-wrap:anywhere]">
                    <strong className="font-[650]">{event.display_name}</strong> {eventText(event, t)}
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
