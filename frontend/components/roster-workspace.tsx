"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  type Group,
  type RosterEntry,
  type UpdateCourseMemberRequest,
} from "../lib/api";
import {
  beginTeacherEnter,
  endTeacherEnter,
  teacherLeavesSettled,
} from "../lib/teacher-visit";
import { useT } from "./locale";
import { PageAction } from "./page-action";
import { IconArrowRight } from "./quiet-icons";
import { useSession } from "./session-provider";
import cards from "./knowledge/brainform-workspace.module.css";
import {
  ModuleCard,
  ModuleGrid,
  ModuleList,
  ModuleRow,
} from "./studyform-layout";
import { UserAvatar } from "./user-avatar";
import { ErrorNotice, LoadingCard, PageIntro } from "./ui";

type Draft = { display_name: string; group_name: string };

/** A password produced by a reset, held only until the page is reloaded. */
type IssuedPassword = { user_id: string; username: string; password: string };

export function RosterWorkspace() {
  const t = useT();
  const { api, user } = useSession();
  const router = useRouter();
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

  const load = useCallback(
    async (gate = true) => {
      if (!courseId) {
        setLoading(false);
        return;
      }
      // Only the first read hides the page. A reload after a row action keeps
      // the list on screen, because swapping it for a loading card unmounts
      // everything below the fold and throws the reader back to the top of a
      // list they were working halfway down.
      if (gate) setLoading(true);
      setError(null);
      try {
        const [roster, courseGroups] = await Promise.all([
          api.courseRoster(courseId),
          api.groups(courseId),
        ]);
        setEntries(roster.entries ?? []);
        setGroups(courseGroups);
      } catch (cause) {
        setError(cause);
      } finally {
        setLoading(false);
      }
    },
    [api, courseId],
  );

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
        await load(false);
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

  const enterGroup = useCallback(
    async (group: Group, joined: boolean) => {
      setBusy(group.id);
      setError(null);
      beginTeacherEnter();
      try {
        // A roster that is already open may still be deleting the previous
        // visit. Join only after that delete finishes, or it removes the row
        // this click just created.
        await teacherLeavesSettled();
        // Joining is what opens the group's workspace, so the two are one
        // action rather than a state to set and then act on.
        if (!joined) {
          await api.joinGroupAsTeacher(group.id);
        }
        // Refresh after the student route is current. Refreshing while this
        // Accounts page is still open makes the shell treat the visit as over
        // and delete it before the group can load.
        router.push(`/student/groups/${group.id}`);
      } catch (cause) {
        endTeacherEnter();
        setError(cause);
        setBusy(null);
      }
    },
    [api, router],
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

  // Removed accounts keep their work and can come back, so they are folded
  // away under their own heading instead of being deleted.
  const current = entries.filter((entry) => entry.status !== "inactive");
  const removed = entries.filter((entry) => entry.status === "inactive");

  function memberRow(entry: RosterEntry) {
    const pending = busy === entry.user_id;
    if (editing === entry.user_id) {
      return (
        <div className="list-row account-row" key={entry.user_id}>
          <form
            id={`roster-edit-${entry.user_id}`}
            className="stack-form account-edit"
            aria-busy={pending}
            onSubmit={(event) => {
              event.preventDefault();
              void mutate(entry, {
                display_name: draft.display_name,
                ...(draft.group_name ? { group_name: draft.group_name } : {}),
              });
            }}
          >
            <label>
              <span>{t("displayNameLabel")}</span>
              <input
                value={draft.display_name}
                disabled={pending}
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
                list="roster-group-names"
                value={draft.group_name}
                disabled={pending}
                maxLength={200}
                onChange={(event) =>
                  setDraft((previous) => ({
                    ...previous,
                    group_name: event.target.value,
                  }))
                }
              />
            </label>
            <div className="button-row">
              <PageAction
                name="back"
                onClick={() => setEditing(null)}
                disabled={pending}
              />
              <PageAction
                name="done"
                form={`roster-edit-${entry.user_id}`}
                disabled={pending}
              />
            </div>
          </form>
        </div>
      );
    }
    return (
      <div className="list-row account-row" key={entry.user_id}>
        <span className="roster-identity">
          <UserAvatar
            avatar={entry.avatar}
            name={entry.display_name}
            userId={entry.user_id}
          />
          <span>
            <span className="roster-headline">
              <strong>{entry.display_name}</strong>
              <small className="roster-username">{entry.username}</small>
              {/* Active is the normal state, and removed accounts are folded
                  away under their own heading, so only they carry a word. */}
              {entry.status === "active" ? null : (
                <small className="roster-status">{t("statusInactive")}</small>
              )}
            </span>
            <span className="group-label">{groupSummary(entry)}</span>
            {issued && issued.user_id === entry.user_id ? (
              <small role="status">
                {t("resetPasswordIssued", {
                  username: issued.username,
                })}
                : <code>{issued.password}</code>{" "}
              </small>
            ) : null}
          </span>
        </span>
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
            {entry.user_id === user?.id ? null : (
              <button
                className="inline-button"
                type="button"
                disabled={pending}
                onClick={() => {
                  if (
                    entry.status === "active" &&
                    !window.confirm(t("removeConfirm"))
                  ) {
                    return;
                  }
                  void mutate(entry, {
                    status: entry.status === "active" ? "inactive" : "active",
                  });
                }}
              >
                {entry.status === "active"
                  ? t("removeAccount")
                  : t("reactivateAccount")}
              </button>
            )}
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
  }

  return (
    <div className="account-layout">
      <PageIntro title={t("accounts")} />
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}

      <ModuleGrid>
        <ModuleCard
          title={t("members")}
          count={current.length}
          labelledBy="accounts-members"
          empty={
            current.length || removed.length ? undefined : t("rosterEmpty")
          }
        >
          {current.length || removed.length ? (
            <>
              <div className="compact-list">
                {current.map(memberRow)}
                <datalist id="roster-group-names">
                  {groupNames.map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>
              </div>
              {removed.length ? (
                <details className="roster-removed">
                  <summary>
                    {t("removedMembers")} · {removed.length}
                  </summary>
                  <div className="compact-list">{removed.map(memberRow)}</div>
                </details>
              ) : null}
            </>
          ) : undefined}
        </ModuleCard>

        <ModuleCard
          title={t("groups")}
          count={groups.length}
          labelledBy="accounts-groups"
          empty={groups.length ? undefined : t("rosterNoGroups")}
        >
          {groups.length ? (
            <ModuleList>
              {groups.map((group) => {
                const joined = ownGroupIds.has(group.id);
                return (
                  <ModuleRow
                    id={`roster-group-${group.id}`}
                    key={group.id}
                    title={group.name}
                    action={
                      <button
                        className={cards.iconButton}
                        type="button"
                        disabled={busy === group.id}
                        aria-label={t("enter")}
                        data-ui-guide="roster.openGroup"
                        onClick={() => void enterGroup(group, joined)}
                      >
                        <IconArrowRight />
                      </button>
                    }
                  />
                );
              })}
            </ModuleList>
          ) : undefined}
        </ModuleCard>
      </ModuleGrid>
    </div>
  );
}
