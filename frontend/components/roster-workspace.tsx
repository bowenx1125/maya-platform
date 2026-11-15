"use client";

import { LIST_CARD_LIFT } from "./agent-chrome";
import { Button, PRESS_MOTION, WORKSPACE_ACTION_SIZE } from "./ui/button";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  type Group,
  type RosterEntry,
  type UpdateCourseMemberRequest,
} from "../lib/api";
import {
  beginTeacherEnter,
  endTeacherEnter,
  noteVisitRenewed,
  teacherLeavesSettled,
} from "../lib/teacher-visit";
import { useT } from "../lib/i18n";
import { PageAction, pageActionClass } from "./page-action";
import { WorkspaceIcon } from "./workspace-icon";
import {
  IconArrowRight,
  IconEdit,
  IconRecycle,
  IconRefresh,
  IconTrash,
} from "./quiet-icons";
import { useSession } from "./session-provider";
import { UserAvatar } from "./user-avatar";
import { ErrorNotice, LoadingCard } from "./ui";
import styles from "./roster-workspace.module.css";
import { PageBanner } from "./page-banner";
import { Input } from "./ui/input";
import { Card } from "./ui/card";
import { GroupSortKey, GroupStudentCount } from "./group-sort-key";
import {
  byName,
  countGroupStudents,
  GROUP_SORT_STORAGE_KEY,
  parseGroupSort,
  sortGroups,
  type GroupSortOrder,
} from "../lib/group-sort";

type Draft = { display_name: string; group_name: string };

/** A password produced by a reset, held only until the page is reloaded. */
type IssuedPassword = { user_id: string; username: string; password: string };

const POLAROID_COLORS = ["#FFE14D", "#A3E635", "#67E8F9"] as const;

export function RosterWorkspace() {
  const t = useT();
  const { api, user, refresh, selectTeacherCourse } = useSession();
  const [adding, setAdding] = useState(false);
  const [className, setClassName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<unknown>(null);
  const teacherIds = (user?.courses ?? [])
    .filter((item) => item.role === "teacher")
    .map((item) => item.course_id)
    .join(",");
  const courseId = teacherIds.split(",")[0] || undefined;
  async function addClass(event: FormEvent) {
    event.preventDefault();
    if (creating || !className.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const created = await api.createClass(className.trim());
      await refresh();
      await selectTeacherCourse(created.id);
      setAdding(false);
      setClassName("");
    } catch (cause) {
      setCreateError(cause);
    } finally {
      setCreating(false);
    }
  }
  return (
    <div className={`account-layout ${styles.layout}`}>
      <PageBanner title={t("accounts")}>
        <button
          type="button"
          className={pageActionClass("new")}
          disabled={creating}
          onClick={() => {
            setAdding(true);
            setCreateError(null);
          }}
        >
          <WorkspaceIcon name="new" size={16} />
          <span>Add Class</span>
        </button>
      </PageBanner>
      {adding ? (
        <Card className="px-5">
          <form
            className="stack-form"
            onSubmit={(event) => void addClass(event)}
          >
            <label>
              <span>Class name</span>
              <Input
                value={className}
                onChange={(event) => setClassName(event.target.value)}
                maxLength={200}
                disabled={creating}
                required
                autoFocus
              />
            </label>
            {createError ? <ErrorNotice error={createError} /> : null}
            <div className="button-row">
              <Button
                type="submit"
                busy={creating}
                disabled={!className.trim()}
                className={WORKSPACE_ACTION_SIZE}
              >
                {creating ? (
                  <span className="spinner" aria-hidden="true" />
                ) : null}
                {creating ? "Creating…" : "Create class"}
              </Button>
              <Button
                variant="neutral"
                disabled={creating}
                onClick={() => setAdding(false)}
                className={WORKSPACE_ACTION_SIZE}
              >
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      ) : null}
      <ClassRosterWorkspace
        key={`${user?.id}:${courseId}`}
        courseId={courseId}
      />
    </div>
  );
}

function ClassRosterWorkspace({ courseId }: { courseId: string | undefined }) {
  const t = useT();
  const router = useRouter();
  const { api, refresh, user } = useSession();
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
  const [filter, setFilter] = useState("");
  const [groupSort, setGroupSort] = useState<GroupSortOrder>("name");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        setGroupSort(
          parseGroupSort(localStorage.getItem(GROUP_SORT_STORAGE_KEY)),
        );
      } catch {
        // Storage may be unavailable; keep the default for this page.
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  function changeGroupSort(order: GroupSortOrder) {
    setGroupSort(order);
    try {
      localStorage.setItem(GROUP_SORT_STORAGE_KEY, order);
    } catch {
      // The selected order still works when storage is unavailable.
    }
  }

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
        // Arriving here ends any group visit; list members once that leave
        // is done, or the caller still shows inside the group they just left.
        await teacherLeavesSettled();
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

  // Deleting is real: the account, its sign-in and its private work go.
  const deleteAccounts = useCallback(
    async (targets: RosterEntry[]) => {
      if (!courseId || !targets.length) return;
      setBusy(targets.length === 1 ? targets[0].user_id : "cleanup");
      setError(null);
      try {
        for (const entry of targets) {
          await api.deleteCourseMember(courseId, entry.user_id);
        }
        setEditing(null);
        await load(false);
      } catch (cause) {
        setError(cause);
        await load(false);
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

  // Enter registers one temporary membership for this teacher, then opens the
  // group's Studyform. beginTeacherEnter keeps the roster shell from deleting
  // that row while the session refresh is still on this page.
  const onGroupPress = useCallback(
    async (group: Group) => {
      setBusy(group.id);
      setError(null);
      beginTeacherEnter();
      try {
        await teacherLeavesSettled();
        await api.joinGroupAsTeacher(group.id);
        noteVisitRenewed(group.id);
        await refresh?.();
        router.push(`/student/agents?group_id=${encodeURIComponent(group.id)}`);
      } catch (cause) {
        endTeacherEnter();
        setError(cause);
      } finally {
        setBusy(null);
      }
    },
    [api, refresh, router],
  );

  if (loading) return <LoadingCard />;

  const groupNames = Array.from(
    new Set(groups.map((group) => group.name)),
  ).sort();

  function groupSummary(entry: RosterEntry) {
    const names = (entry.groups ?? []).map((group) => group.name);
    return entry.role === "teacher"
      ? t("rosterTeachers")
      : names.length > 0
        ? names.join(", ")
        : "—";
  }

  // Accounts removed before deletion was real stay folded under their own
  // heading, where they can be restored or deleted for good.
  const query = filter.trim().toLocaleLowerCase();
  const matches = (entry: RosterEntry) =>
    !query ||
    [
      entry.display_name,
      entry.username,
      ...(entry.groups ?? []).map((group) => group.name),
    ].some((value) => value.toLocaleLowerCase().includes(query));
  const current = entries.filter(
    (entry) => entry.status !== "inactive" && matches(entry),
  );
  const removed = entries.filter(
    (entry) => entry.status === "inactive" && matches(entry),
  );
  const removedAll = entries.filter((entry) => entry.status === "inactive");

  // Members are listed group by group, groups by name and people by name
  // inside each; legacy ungrouped students and teachers stay separate.
  const sections = new Map<string, RosterEntry[]>();
  for (const entry of current.filter((entry) => entry.role !== "teacher")) {
    const [first] = (entry.groups ?? [])
      .map((group) => group.name)
      .sort(byName);
    const key = first ?? "";
    sections.set(key, [...(sections.get(key) ?? []), entry]);
  }
  const memberSections = [...sections.entries()]
    .sort(([left], [right]) =>
      left === "" ? 1 : right === "" ? -1 : byName(left, right),
    )
    .map(([key, members]) => ({
      key: `group:${key}`,
      name: key || t("homeStudentsCount"),
      members: [...members].sort((left, right) =>
        byName(left.display_name, right.display_name),
      ),
    }));

  const teachers = current.filter((entry) => entry.role === "teacher");
  if (teachers.length) {
    memberSections.push({
      key: "teachers",
      name: t("rosterTeachers"),
      members: teachers.sort((left, right) =>
        byName(left.display_name, right.display_name),
      ),
    });
  }

  function memberRow(entry: RosterEntry, inSection = false) {
    const pending = busy === entry.user_id || busy === "cleanup";
    if (editing === entry.user_id) {
      return (
        <div
          className={`list-row account-row ${styles.row}`}
          key={entry.user_id}
        >
          <form
            id={`roster-edit-${entry.user_id}`}
            className={`stack-form account-edit ${styles.editForm}`}
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
      <div className={`list-row account-row ${styles.row}`} key={entry.user_id}>
        <span className={`roster-identity ${styles.identity}`}>
          <UserAvatar
            avatar={entry.avatar}
            name={entry.display_name}
            userId={entry.user_id}
          />
          <span className={styles.identityMeta}>
            <span className={`roster-headline ${styles.headline}`}>
              <strong>{entry.display_name}</strong>
              <small className={`roster-username ${styles.username}`}>
                {entry.username}
              </small>
              {/* Active is the normal state, and removed accounts are folded
                  away under their own heading, so only they carry a word. */}
              {entry.status === "active" ? null : (
                <small className={`roster-status ${styles.status}`}>
                  {t("statusInactive")}
                </small>
              )}
            </span>
            {/* Under a group's heading the group goes without saying; a
                second group, or a removed account, still names them. */}
            {inSection && (entry.groups?.length ?? 0) <= 1 ? null : (
              <span className={`group-label ${styles.groupLabel}`}>
                {groupSummary(entry)}
              </span>
            )}
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
          <div className={`button-row ${styles.acts}`}>
            <button
              className={`${styles.sticker} ${styles.stickerEdit} ${PRESS_MOTION}`}
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
              <IconEdit size={12} />
              <span>{t("editMember")}</span>
            </button>
            {entry.user_id === user?.id ? null : (
              <>
                {entry.status === "active" ? null : (
                  <button
                    className={`${styles.sticker} ${styles.stickerRestore} ${PRESS_MOTION}`}
                    type="button"
                    disabled={pending}
                    onClick={() => void mutate(entry, { status: "active" })}
                  >
                    <IconRecycle size={12} />
                    <span>{t("reactivateAccount")}</span>
                  </button>
                )}
                <button
                  className={`${styles.sticker} ${styles.stickerRem} ${PRESS_MOTION}`}
                  type="button"
                  disabled={pending}
                  onClick={() => {
                    if (
                      !window.confirm(
                        t("deleteConfirm", { name: entry.display_name }),
                      )
                    )
                      return;
                    void deleteAccounts([entry]);
                  }}
                >
                  <IconTrash size={12} />
                  <span>{t("deleteAccount")}</span>
                </button>
              </>
            )}
            <button
              className={`${styles.sticker} ${styles.stickerReset} ${PRESS_MOTION}`}
              type="button"
              disabled={pending}
              onClick={() => void resetPassword(entry)}
            >
              <IconRefresh size={12} />
              <span>{t("resetPassword")}</span>
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  const groupCounts = countGroupStudents(entries);
  const sortedGroups = sortGroups(groups, groupCounts, groupSort);

  return (
    <>
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}

      <div className={styles.grid}>
        <section
          className={styles.card}
          aria-labelledby="accounts-members"
          role="region"
        >
          <div className={styles.head}>
            <h2 id="accounts-members" className={styles.tapeTitle}>
              {t("members")}
            </h2>
            <span className={styles.badge} aria-hidden="true">
              {current.length}
            </span>
          </div>
          {entries.length ? (
            <input
              className={styles.filter}
              type="search"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder={t("filterMembers")}
              aria-label={t("filterMembers")}
            />
          ) : null}
          {current.length || removed.length ? (
            <>
              <div className={`roster-sections ${styles.sections}`}>
                {memberSections.map((section) => (
                  <section
                    className={`roster-section ${styles.section}`}
                    key={section.key}
                  >
                    <h3
                      className={`roster-section-title ${styles.sectionTitle}`}
                    >
                      <span className={styles.sectionTape}>{section.name}</span>
                      <small className={styles.sectionCount}>
                        {section.members.length}
                      </small>
                    </h3>
                    <div className={`compact-list ${styles.rows}`}>
                      {section.members.map((entry) => memberRow(entry, true))}
                    </div>
                  </section>
                ))}
                <datalist id="roster-group-names">
                  {groupNames.map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>
              </div>
              {removed.length ? (
                <details className={`roster-removed ${styles.removed}`}>
                  <summary>
                    {t("removedMembers")} · {removed.length}
                  </summary>
                  <div
                    className={`compact-list ${styles.rows} ${styles.removedBody}`}
                  >
                    {removed.map((entry) => memberRow(entry))}
                  </div>
                  <button
                    className={`${styles.sticker} ${styles.stickerRem} ${styles.cleanup} ${PRESS_MOTION}`}
                    type="button"
                    disabled={busy !== null}
                    aria-busy={busy === "cleanup" || undefined}
                    onClick={() => {
                      if (
                        !window.confirm(
                          t("cleanupConfirm", { count: removedAll.length }),
                        )
                      )
                        return;
                      void deleteAccounts(removedAll);
                    }}
                  >
                    <IconTrash size={12} />
                    <span>{t("cleanupRemoved")}</span>
                  </button>
                </details>
              ) : null}
            </>
          ) : (
            <p className={styles.empty}>
              {entries.length ? t("noMembersMatch") : t("rosterEmpty")}
            </p>
          )}
        </section>

        <section
          className={styles.card}
          aria-labelledby="accounts-groups"
          role="region"
        >
          <div className={`${styles.head} ${styles.groupsHead}`}>
            <h2 id="accounts-groups" className={styles.tapeTitle}>
              {t("groups")}
            </h2>
            <span
              className={`${styles.badge} ${styles.badgeCyan}`}
              aria-hidden="true"
            >
              {groups.length}
            </span>
            <GroupSortKey order={groupSort} onChange={changeGroupSort} />
          </div>
          {groups.length ? (
            <ul className={styles.polarList}>
              {sortedGroups.map((group, index) => (
                <li key={group.id} className={LIST_CARD_LIFT}>
                  <button
                    className={styles.polar}
                    type="button"
                    id={`roster-group-${group.id}`}
                    aria-label={t("enter")}
                    aria-busy={busy === group.id || undefined}
                    disabled={busy === group.id}
                    data-ui-guide="roster.openGroup"
                    style={{
                      background:
                        POLAROID_COLORS[index % POLAROID_COLORS.length],
                    }}
                    onClick={() => onGroupPress(group)}
                  >
                    <span className={styles.polarTape} aria-hidden="true" />
                    <span className={styles.polarNameRow}>
                      <span className={styles.polarName}>{group.name}</span>
                      <GroupStudentCount
                        count={groupCounts.get(group.id) ?? 0}
                      />
                    </span>
                    <span className={styles.polarArrow} aria-hidden="true">
                      <IconArrowRight size={16} />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.empty}>{t("rosterNoGroups")}</p>
          )}
        </section>
      </div>
    </>
  );
}
