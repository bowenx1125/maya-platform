"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  type Course,
  type Group,
  type RosterEntry,
  type UpdateCourseMemberRequest,
} from "../lib/api";
import { roleLabel } from "../lib/i18n";
import { useLocale, useT } from "./locale";
import { useSession } from "./session-provider";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
  StatusBadge,
} from "./ui";

type Draft = { display_name: string; group_name: string };

/** A password produced by a reset, held only until the page is reloaded. */
type IssuedPassword = { user_id: string; username: string; password: string };

function sourceKey(source: string) {
  if (source === "catalog") return "sourceCatalog" as const;
  if (source === "observer") return "sourceObserver" as const;
  return "sourceDatabase" as const;
}

export function RosterWorkspace() {
  const t = useT();
  const { locale } = useLocale();
  const { api, user } = useSession();
  const [course, setCourse] = useState<Course | null>(null);
  const [entries, setEntries] = useState<RosterEntry[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>({
    display_name: "",
    group_name: "",
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [issued, setIssued] = useState<IssuedPassword | null>(null);

  const courseId = useMemo(
    () => user?.courses.find((item) => item.role === "teacher")?.course_id,
    [user],
  );

  const load = useCallback(async () => {
    if (!courseId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [courses, roster, courseGroups] = await Promise.all([
        api.courses(),
        api.courseRoster(courseId),
        api.groups(courseId),
      ]);
      setCourse(courses.find((item) => item.id === courseId) ?? null);
      setEntries(roster.entries ?? []);
      setGroups(courseGroups);
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, courseId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const mutate = useCallback(
    async (entry: RosterEntry, body: UpdateCourseMemberRequest) => {
      if (!courseId) return;
      setBusy(entry.user_id);
      setError(null);
      try {
        await api.updateCourseMember(courseId, entry.user_id, body);
        setEditing(null);
        await load();
      } catch (cause) {
        setError(cause);
      } finally {
        setBusy(null);
      }
    },
    [api, courseId, load],
  );

  const resetPassword = useCallback(
    async (entry: RosterEntry) => {
      if (!courseId) return;
      setBusy(entry.user_id);
      setError(null);
      try {
        const result = await api.resetStudentPassword(courseId, entry.user_id);
        setIssued({
          user_id: entry.user_id,
          username: result.username,
          password: result.password,
        });
      } catch (cause) {
        setError(cause);
      } finally {
        setBusy(null);
      }
    },
    [api, courseId],
  );

  const toggleGroup = useCallback(
    async (group: Group, joined: boolean) => {
      setBusy(group.id);
      setError(null);
      try {
        if (joined) {
          await api.leaveGroupAsTeacher(group.id);
        } else {
          await api.joinGroupAsTeacher(group.id);
        }
        await load();
      } catch (cause) {
        setError(cause);
      } finally {
        setBusy(null);
      }
    },
    [api, load],
  );

  if (loading) return <LoadingCard />;

  const self = entries.find((entry) => entry.user_id === user?.id);
  const ownGroupIds = new Set(self?.groups?.map((group) => group.id) ?? []);
  const groupNames = Array.from(
    new Set(groups.map((group) => group.name)),
  ).sort();

  function groupSummary(entry: RosterEntry) {
    const names = (entry.groups ?? []).map((group) => group.name);
    return names.length > 0 ? names.join(", ") : t("rosterNoGroup");
  }

  return (
    <>
      <PageIntro
        eyebrow={t("accountsEyebrow")}
        title={course?.name ?? t("accounts")}
        description={t("accountsLede")}
      />
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}

      <SectionCard title={t("accounts")}>
        {entries.length === 0 ? (
          <EmptyCard title={t("rosterEmpty")} />
        ) : (
          <div className="compact-list">
            {entries.map((entry) => {
              const pending = busy === entry.user_id;
              if (editing === entry.user_id) {
                return (
                  <div className="list-row" key={entry.user_id}>
                    <form
                      className="stack-form"
                      onSubmit={(event) => {
                        event.preventDefault();
                        void mutate(entry, {
                          display_name: draft.display_name,
                          ...(draft.group_name
                            ? { group_name: draft.group_name }
                            : {}),
                        });
                      }}
                    >
                      <label>
                        <span>{t("displayNameLabel")}</span>
                        <input
                          value={draft.display_name}
                          maxLength={200}
                          onChange={(event) =>
                            setDraft((previous) => ({
                              ...previous,
                              display_name: event.target.value,
                            }))
                          }
                          required
                        />
                      </label>
                      <label>
                        <span>{t("groupNameLabel")}</span>
                        <input
                          aria-describedby="roster-group-hint"
                          list="roster-group-names"
                          value={draft.group_name}
                          maxLength={200}
                          onChange={(event) =>
                            setDraft((previous) => ({
                              ...previous,
                              group_name: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <small className="muted" id="roster-group-hint">
                        {t("groupNameHint")}
                      </small>
                      <div className="button-row">
                        <button
                          className="inline-button"
                          type="submit"
                          disabled={pending}
                        >
                          {t("save")}
                        </button>
                        <button
                          className="inline-button"
                          type="button"
                          disabled={pending}
                          onClick={() => setEditing(null)}
                        >
                          {t("cancel")}
                        </button>
                      </div>
                    </form>
                  </div>
                );
              }
              return (
                <div className="list-row" key={entry.user_id}>
                  <span>
                    <strong>{entry.display_name}</strong>
                    <small>
                      {entry.username} · {roleLabel(entry.role, locale)} ·{" "}
                      {t(sourceKey(entry.source))}
                    </small>
                    <small>{groupSummary(entry)}</small>
                    {entry.editable ? null : (
                      <small className="muted">{t("sourceLockedHint")}</small>
                    )}
                    {issued && issued.user_id === entry.user_id ? (
                      <small role="status">
                        {t("resetPasswordIssued", {
                          username: issued.username,
                        })}
                        : <code>{issued.password}</code>{" "}
                        {t("resetPasswordHint")}
                      </small>
                    ) : null}
                  </span>
                  <StatusBadge
                    status={entry.status}
                    tone={entry.status === "active" ? "good" : "neutral"}
                  />
                  {entry.editable ? (
                    <div className="button-row">
                      <button
                        className="inline-button"
                        type="button"
                        disabled={pending}
                        onClick={() => {
                          setEditing(entry.user_id);
                          setDraft({
                            display_name: entry.display_name,
                            group_name: entry.groups?.[0]?.name ?? "",
                          });
                        }}
                      >
                        {t("editMember")}
                      </button>
                      <button
                        className="inline-button"
                        type="button"
                        disabled={pending}
                        onClick={() => {
                          if (
                            entry.status === "active" &&
                            !window.confirm(t("deactivateConfirm"))
                          ) {
                            return;
                          }
                          void mutate(entry, {
                            status:
                              entry.status === "active" ? "inactive" : "active",
                          });
                        }}
                      >
                        {entry.status === "active"
                          ? t("deactivateAccount")
                          : t("reactivateAccount")}
                      </button>
                      <button
                        className="inline-button"
                        type="button"
                        disabled={pending}
                        onClick={() => void resetPassword(entry)}
                      >
                        {t("resetPassword")}
                      </button>
                    </div>
                  ) : null}
                </div>
              );
            })}
            <datalist id="roster-group-names">
              {groupNames.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </div>
        )}
      </SectionCard>

      <SectionCard title={t("walkInTitle")} description={t("walkInLede")}>
        {groups.length === 0 ? (
          <EmptyCard title={t("rosterNoGroup")} />
        ) : (
          <div className="compact-list">
            {groups.map((group) => {
              const joined = ownGroupIds.has(group.id);
              return (
                <div className="list-row" key={group.id}>
                  <span>
                    <strong>{group.name}</strong>
                    {joined ? <small>{t("inThisGroup")}</small> : null}
                  </span>
                  <button
                    className="inline-button"
                    type="button"
                    disabled={busy === group.id}
                    onClick={() => void toggleGroup(group, joined)}
                  >
                    {joined ? t("leaveGroup") : t("joinGroup")}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </SectionCard>
    </>
  );
}
