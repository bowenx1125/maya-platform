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
import { useT } from "../lib/i18n";
import { PageAction } from "./page-action";
import {
  IconArrowRight,
  IconEdit,
  IconRecycle,
  IconRefresh,
  IconTrash,
} from "./quiet-icons";
import { useSession } from "./session-provider";
import { UserAvatar } from "./user-avatar";
import { ErrorNotice, LoadingCard, PageIntro } from "./ui";
import styles from "./roster-workspace.module.css";

type Draft = { display_name: string; group_name: string };

/** A password produced by a reset, held only until the page is reloaded. */
type IssuedPassword = { user_id: string; username: string; password: string };

const POLAROID_COLORS = ["#FFE14D", "#A3E635", "#67E8F9"] as const;

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
    async (group: Group) => {
      setBusy(group.id);
      setError(null);
      beginTeacherEnter();
      try {
        // A roster that is already open may still be deleting the previous
        // visit. Join only after that delete finishes, or it removes the row
        // this click just created.
        await teacherLeavesSettled();
        // Joining is what opens the group's workspace, so the two are one
        // action rather than a state to set and then act on. Join even when
        // this roster lists the caller in the group: it may have loaded
        // before that leave finished. Joining is idempotent.
        await api.joinGroupAsTeacher(group.id);
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

  // Members are listed group by group, groups by name and people by name
  // inside each; anyone without a group comes last.
  const byName = (left: string, right: string) =>
    left.localeCompare(right, undefined, {
      numeric: true,
      sensitivity: "base",
    });
  const sections = new Map<string, RosterEntry[]>();
  for (const entry of current) {
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
      key,
      name: key || t("rosterNoGroup"),
      members: [...members].sort((left, right) =>
        byName(left.display_name, right.display_name),
      ),
    }));

  function memberRow(entry: RosterEntry, inSection = false) {
    const pending = busy === entry.user_id;
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
      <div
        className={`list-row account-row ${styles.row}`}
        key={entry.user_id}
      >
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
              className={`${styles.sticker} ${styles.stickerEdit}`}
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
              <button
                className={`${styles.sticker} ${
                  entry.status === "active"
                    ? styles.stickerRem
                    : styles.stickerRestore
                }`}
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
                {entry.status === "active" ? (
                  <IconTrash size={12} />
                ) : (
                  <IconRecycle size={12} />
                )}
                <span>
                  {entry.status === "active"
                    ? t("removeAccount")
                    : t("reactivateAccount")}
                </span>
              </button>
            )}
            <button
              className={`${styles.sticker} ${styles.stickerReset}`}
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

  const sortedGroups = [...groups].sort((left, right) =>
    byName(left.name, right.name),
  );

  return (
    <div className={`account-layout ${styles.layout}`}>
      <PageIntro title={t("accounts")} />
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
                  <div className={`compact-list ${styles.rows} ${styles.removedBody}`}>
                    {removed.map((entry) => memberRow(entry))}
                  </div>
                </details>
              ) : null}
            </>
          ) : (
            <p className={styles.empty}>{t("rosterEmpty")}</p>
          )}
        </section>

        <section
          className={styles.card}
          aria-labelledby="accounts-groups"
          role="region"
        >
          <div className={styles.head}>
            <h2 id="accounts-groups" className={styles.tapeTitle}>
              {t("groups")}
            </h2>
            <span
              className={`${styles.badge} ${styles.badgeCyan}`}
              aria-hidden="true"
            >
              {groups.length}
            </span>
          </div>
          {groups.length ? (
            <ul className={styles.polarList}>
              {sortedGroups.map((group, index) => (
                <li key={group.id}>
                  <button
                    className={styles.polar}
                    type="button"
                    id={`roster-group-${group.id}`}
                    disabled={busy === group.id}
                    aria-label={t("enter")}
                    data-ui-guide="roster.openGroup"
                    style={{
                      background:
                        POLAROID_COLORS[index % POLAROID_COLORS.length],
                    }}
                    onClick={() => void enterGroup(group)}
                  >
                    <span className={styles.polarTape} aria-hidden="true" />
                    <span className={styles.polarName}>{group.name}</span>
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
    </div>
  );
}
