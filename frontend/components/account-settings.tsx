"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { bowenLandingGroup, type BowenGroup } from "../lib/bowen-student";
import { cachedCall, requestCacheIdentity } from "../lib/request-cache";
import { PlatformApiError } from "../lib/api/platform";
import { useT } from "../lib/i18n";
import { useSession } from "./session-provider";
import { ErrorNotice, SectionCard, StickerBadge } from "./ui";
import { BUSY_MOTION_PRIMARY, PRESS_MOTION } from "./ui/button";
import { USER_AVATAR_CHOICES, UserAvatar } from "./user-avatar";

/** The profile module: a white card with a lime ring and a tape title. */
const CARD =
  "relative mb-0 rounded-xl border-[3px] border-ink bg-white px-6 pt-[52px] pb-5 font-body text-ink shadow-[0_0_0_3px_#A3E635,8px_8px_0_3px_#111] max-[640px]:px-4 [&>.section-card-header]:absolute [&>.section-card-header]:border-0 [&>.section-card-header]:p-0 [&>.section-card-header]:-top-5 [&>.section-card-header]:left-4 [&>.section-card-header]:m-0 [&>.section-card-header_h2]:-rotate-1 [&>.section-card-header_h2]:border-[3px] [&>.section-card-header_h2]:border-ink [&>.section-card-header_h2]:bg-white [&>.section-card-header_h2]:bg-[linear-gradient(90deg,#FFE14D_0_8px,transparent_8px_calc(100%-8px),#FFE14D_calc(100%-8px))] [&>.section-card-header_h2]:px-4 [&>.section-card-header_h2]:py-0.5 [&>.section-card-header_h2]:font-display [&>.section-card-header_h2]:text-[22px] [&>.section-card-header_h2]:font-extrabold [&>.section-card-header_h2]:tracking-normal [&>.section-card-header_h2]:text-ink";
const PANEL = "grid min-w-0 content-start gap-4 py-1 pr-8 max-[640px]:pr-0";
const HEADING = "m-0 font-display text-lg font-extrabold text-ink";
const LABEL = "grid min-w-0 gap-1.5 text-[13px] font-bold text-ink";
const FIELD =
  "min-h-[46px] max-[640px]:min-h-[51px] w-full rounded-lg border-[3px] border-ink bg-white px-3 py-2 font-body text-sm text-ink focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-[#67E8F9] disabled:opacity-60";
const SAVED =
  "rotate-[-3deg] rounded border-2 border-ink bg-[#A3E635] px-2 py-px text-xs font-extrabold text-ink shadow-[2px_2px_0_#111]";
/** Save as an arcade key: pink, inked; shared PRESS_MOTION. */
const PRESS = `inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border-[3px] border-ink bg-[#FF4D8D] px-5 font-display text-base font-extrabold text-ink hover:bg-[#FF4D8D] disabled:opacity-60 disabled:aria-busy:opacity-100 ${PRESS_MOTION} ${BUSY_MOTION_PRIMARY}`;

export function AccountSettings({ onSaved }: { onSaved?: () => void }) {
  const { user, identityGeneration } = useSession();
  return user ? (
    <AccountSettingsForm
      key={`${user.id}:${identityGeneration}`}
      onSaved={onSaved}
    />
  ) : null;
}

function AccountSettingsForm({ onSaved }: { onSaved?: () => void }) {
  const t = useT();
  const { api, identityGeneration, refresh, user } = useSession();
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const [avatar, setAvatar] = useState<string | null>(user?.avatar ?? null);
  const [name, setName] = useState(user?.display_name ?? "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState<
    "avatar" | "name" | "group" | "class" | "password" | null
  >(null);
  const [error, setError] = useState<unknown>(null);
  // U3: the confirm field the mismatch error points at, by number.
  const [mismatch, setMismatch] = useState(false);
  const [saved, setSaved] = useState<
    "avatar" | "name" | "group" | "class" | "password" | null
  >(null);
  // A student may move to another group the course already has. Teachers
  // visit groups from Accounts instead, so they get no picker.
  const studentCourseIds = (user?.courses ?? [])
    .filter((membership) => membership.role === "student")
    .map((membership) => membership.course_id)
    .join(",");
  const currentGroupId = user?.groups?.[0]?.group_id;
  const [groupNames, setGroupNames] = useState<string[]>([]);
  const [currentGroup, setCurrentGroup] = useState("");
  const [groupChoice, setGroupChoice] = useState("");
  useEffect(() => {
    const activeCourseId = studentCourseIds.split(",").filter(Boolean)[0] ?? "";
    if (!activeCourseId) return;
    // Bowen is in both classes, so the current membership may belong to the
    // other one. Everyone else still needs a group before the picker means
    // anything.
    if (user?.username !== "bowen" && !currentGroupId) return;
    let active = true;
    const membershipIds = (user?.groups ?? []).map((item) => item.group_id);
    const groupReads =
      user?.username === "bowen"
        ? Promise.all(membershipIds.map((groupId) => api.group(groupId)))
        : cachedCall(
            api,
            requestCacheIdentity(user?.id, identityGeneration),
            "group",
            [currentGroupId ?? ""],
            () => api.group(currentGroupId ?? ""),
          ).then((group) => [group]);
    // The group is the page's own read too (shared cache, same key).
    void Promise.all([api.registrationOptions(), groupReads])
      .then(([options, details]) => {
        if (!active) return;
        // The choices are the active class's existing groups; the picker
        // never offers to start a new one. Bowen's session lists the class
        // chosen at login first, which is the class he can move inside.
        const selectedGroups =
          options.classes?.find((item) => item.course_id === activeCourseId)
            ?.groups ??
          (options.course_id === activeCourseId ? options.groups : []);
        const names = selectedGroups
          .map((choice) => choice.name)
          .sort((left, right) =>
            left.localeCompare(right, undefined, {
              numeric: true,
              sensitivity: "base",
            }),
          );
        if (user?.username === "bowen") {
          const inClass = (details as BowenGroup[]).filter(
            (group) => group.course_id === activeCourseId,
          );
          const currentName =
            bowenLandingGroup(inClass, activeCourseId)?.name ?? "";
          setGroupNames(names);
          setCurrentGroup(currentName);
          setGroupChoice(currentName);
          return;
        }
        const group = details[0];
        setGroupNames(names.includes(group.name) ? names : []);
        setCurrentGroup(group.name);
        setGroupChoice(group.name);
      })
      .catch(() => {
        if (active) setGroupNames([]);
      });
    return () => {
      active = false;
    };
  }, [
    api,
    currentGroupId,
    identityGeneration,
    studentCourseIds,
    user?.groups,
    user?.id,
    user?.username,
  ]);
  const [classChoices, setClassChoices] = useState<
    { course_id: string; course_name: string }[]
  >([]);
  const [classChoice, setClassChoice] = useState(
    studentCourseIds.split(",")[0] ?? "",
  );
  useEffect(() => {
    if (!studentCourseIds) return;
    let active = true;
    void api
      .registrationOptions()
      .then((options) => {
        if (active) setClassChoices(options.classes ?? []);
      })
      .catch(() => {
        if (active) setClassChoices([]);
      });
    return () => {
      active = false;
    };
  }, [api, studentCourseIds]);
  async function saveClass(event: FormEvent) {
    event.preventDefault();
    if (busy !== null || !classChoice || classChoice === studentCourseIds)
      return;
    if (
      !window.confirm(
        "Change class? Your existing work stays in the previous class.",
      )
    )
      return;
    setBusy("class");
    setError(null);
    setSaved(null);
    try {
      await api.updateCurrentUser({ course_id: classChoice });
      if (!mounted.current) return;
      await refresh();
    } catch (cause) {
      if (mounted.current) setError(cause);
    } finally {
      if (mounted.current) setBusy(null);
    }
  }
  const groupChanged = groupChoice !== "" && groupChoice !== currentGroup;

  // The server collapses runs of spaces the same way, so a name that only
  // differs by spacing is not offered as a change.
  const typedName = name.split(/\s+/).filter(Boolean).join(" ");
  const nameChanged = typedName !== "" && typedName !== user?.display_name;

  // Picking a scholar is the choice, so it saves there and then. With a
  // separate Save the large preview already showed the new face, and leaving
  // without saving looked done when it was not.
  async function pickAvatar(choice: string) {
    if (busy !== null || choice === avatar) return;
    const previous = avatar;
    setAvatar(choice);
    setBusy("avatar");
    setSaved(null);
    setError(null);
    setMismatch(false);
    try {
      await api.updateCurrentUser({ avatar: choice });
      if (!mounted.current) return;
      await refresh();
      if (!mounted.current) return;
      // The session carries the viewer's own avatar, but the roster and the
      // group's member list were fetched separately and still hold the old
      // one. Without this the person who just picked a scholar is the only
      // one on the page who cannot see it.
      onSaved?.();
      setSaved("avatar");
    } catch (cause) {
      if (!mounted.current) return;
      // The preview never keeps a face the server did not take.
      setAvatar(previous);
      setError(cause);
    } finally {
      if (mounted.current) setBusy(null);
    }
  }

  async function saveName(event: FormEvent) {
    event.preventDefault();
    if (busy !== null || !nameChanged) return;
    setBusy("name");
    setSaved(null);
    setError(null);
    setMismatch(false);
    try {
      await api.updateCurrentUser({ display_name: typedName });
      if (!mounted.current) return;
      await refresh();
      if (!mounted.current) return;
      // The group's member list was fetched on its own and still shows the
      // old name until the page reloads it.
      onSaved?.();
      setName(typedName);
      setSaved("name");
    } catch (cause) {
      if (mounted.current) setError(cause);
    } finally {
      if (mounted.current) setBusy(null);
    }
  }

  async function saveGroup(event: FormEvent) {
    event.preventDefault();
    if (busy !== null || !groupChanged) return;
    // Work stays in the group it was made in, so say so before it goes out
    // of reach.
    if (
      !window.confirm(
        t("groupMoveConfirm", { from: currentGroup, to: groupChoice }),
      )
    )
      return;
    setBusy("group");
    setSaved(null);
    setError(null);
    setMismatch(false);
    try {
      await api.updateCurrentUser({ group_name: groupChoice });
      if (!mounted.current) return;
      // The new membership changes the session's groups, and the home
      // reloads its group from that. onSaved is not called: it still holds
      // the old group, which this account can no longer open.
      await refresh();
      if (!mounted.current) return;
      setCurrentGroup(groupChoice);
      setSaved("group");
    } catch (cause) {
      if (mounted.current) setError(cause);
    } finally {
      if (mounted.current) setBusy(null);
    }
  }

  async function savePassword(event: FormEvent) {
    event.preventDefault();
    setSaved(null);
    setError(null);
    setMismatch(false);
    if (newPassword !== confirmPassword) {
      setMismatch(true);
      setError(new Error(t("registerPasswordMismatch")));
      return;
    }
    setBusy("password");
    try {
      await api.changePassword(currentPassword, newPassword);
      if (!mounted.current) return;
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setSaved("password");
    } catch (cause) {
      if (mounted.current) setError(cause);
    } finally {
      if (mounted.current) setBusy(null);
    }
  }

  // U3: a wrong current password is a field error on that field, not the
  // server "!".
  const wrongCurrent =
    !mismatch &&
    error instanceof PlatformApiError &&
    error.code === "password_incorrect";

  if (!user) return null;

  return (
    <SectionCard
      title={t("profile")}
      className={`account-settings-card ${CARD}`}
    >
      {error ? (
        <ErrorNotice
          id={mismatch ? "password-field-error" : undefined}
          error={error}
          badge={mismatch || wrongCurrent ? 1 : undefined}
        />
      ) : null}
      <div className="grid grid-cols-2 max-[640px]:grid-cols-1">
        <section
          className={`${PANEL} [&_.user-avatar]:!rounded-[8px] [&_.user-avatar]:!border-2 [&_.user-avatar]:!border-solid [&_.user-avatar]:!border-[#111] [&>div>.user-avatar]:!size-14 [&>div>.user-avatar]:!rounded-[10px] [&>div>.user-avatar]:!border-[3px]`}
          aria-labelledby="profile-avatar"
        >
          <div className="flex items-center gap-3.5">
            <UserAvatar
              avatar={avatar}
              name={user.display_name}
              userId={user.id}
              size="lg"
            />
            <div className="grid min-w-0">
              <h3 id="profile-avatar" className={HEADING}>
                {t("userAvatar")}
              </h3>
              <span className="text-[13px] font-semibold text-[#4B5563]">
                {user.display_name}
              </span>
            </div>
            {saved === "avatar" ? (
              <span className={SAVED} role="status">
                {t("saved")}
              </span>
            ) : null}
          </div>
          <form
            className="flex items-end gap-3"
            onSubmit={(event) => void saveName(event)}
          >
            <label className={`${LABEL} flex-1`}>
              <span>{t("displayNameLabel")}</span>
              <input
                className={FIELD}
                value={name}
                maxLength={200}
                required
                autoComplete="nickname"
                disabled={busy !== null}
                onChange={(event) => {
                  setName(event.target.value);
                  if (saved === "name") setSaved(null);
                }}
              />
            </label>
            {/* Save appears once there is a new name to save, so the panel
                stays as quiet as the avatar picker until then. */}
            {nameChanged ? (
              <button
                className={`primary-action ${PRESS}`}
                type="submit"
                disabled={busy !== null}
                aria-busy={busy === "name" || undefined}
              >
                {busy === "name" ? (
                  <span className="spinner" aria-hidden="true" />
                ) : null}
                {t("save")}
              </button>
            ) : saved === "name" ? (
              <span className={SAVED} role="status">
                {t("saved")}
              </span>
            ) : null}
          </form>
          {studentCourseIds && classChoices.length > 0 ? (
            <form
              className="flex items-end gap-3"
              onSubmit={(event) => void saveClass(event)}
            >
              <label className={`${LABEL} flex-1`}>
                <span>Class</span>
                <select
                  className={FIELD}
                  value={classChoice}
                  disabled={busy !== null}
                  onChange={(event) => setClassChoice(event.target.value)}
                >
                  {classChoices.map((choice) => (
                    <option key={choice.course_id} value={choice.course_id}>
                      {choice.course_name}
                    </option>
                  ))}
                </select>
              </label>
              {classChoice !== studentCourseIds ? (
                <button
                  type="submit"
                  className={`primary-action ${PRESS}`}
                  disabled={busy !== null}
                >
                  {t("save")}
                </button>
              ) : null}
            </form>
          ) : null}
          {groupNames.length > 1 ? (
            <form
              className="flex items-end gap-3"
              onSubmit={(event) => void saveGroup(event)}
            >
              <label className={`${LABEL} flex-1`}>
                <span>{t("groupNameLabel")}</span>
                <select
                  className={FIELD}
                  value={groupChoice}
                  disabled={busy !== null}
                  onChange={(event) => {
                    setGroupChoice(event.target.value);
                    if (saved === "group") setSaved(null);
                  }}
                >
                  {groupNames.map((choice) => (
                    <option key={choice} value={choice}>
                      {choice}
                    </option>
                  ))}
                </select>
              </label>
              {groupChanged ? (
                <button
                  className={`primary-action ${PRESS}`}
                  type="submit"
                  disabled={busy !== null}
                  aria-busy={busy === "group" || undefined}
                >
                  {busy === "group" ? (
                    <span className="spinner" aria-hidden="true" />
                  ) : null}
                  {t("save")}
                </button>
              ) : saved === "group" ? (
                <span className={SAVED} role="status">
                  {t("saved")}
                </span>
              ) : null}
            </form>
          ) : null}
          <fieldset
            className="m-0 grid grid-cols-[repeat(4,max-content)] gap-1.5 border-0 p-0"
            disabled={busy !== null}
          >
            <legend className="sr-only">{t("userAvatar")}</legend>
            {USER_AVATAR_CHOICES.map((choice, index) => (
              <label
                className="grid cursor-pointer rounded-[14px] border-[3px] border-transparent p-1 transition-[translate,border-color,background-color] duration-[280ms] ease-[cubic-bezier(0.34,1.4,0.64,1)] focus-within:outline-[3px] focus-within:outline-offset-2 focus-within:outline-[#67E8F9] hover:-translate-y-0.5 hover:bg-[#FFF7CC] [&_.user-avatar]:shadow-[2px_2px_0_#111] data-[selected=true]:[&_.user-avatar]:outline-[3px] data-[selected=true]:[&_.user-avatar]:outline-offset-2 data-[selected=true]:[&_.user-avatar]:outline-[#FF4D8D] data-[selected=true]:[&_.user-avatar]:outline-solid in-disabled:cursor-progress motion-reduce:transition-none motion-reduce:hover:translate-y-0"
                key={choice}
                data-selected={avatar === choice ? "true" : undefined}
              >
                <input
                  className="sr-only"
                  type="radio"
                  name="user-avatar"
                  value={choice}
                  checked={avatar === choice}
                  onChange={() => void pickAvatar(choice)}
                />
                {/* Large enough to tell apart: at 28px the four silhouettes
                    collapsed into one blob and the picker offered four
                    colours rather than eight scholars. */}
                <UserAvatar
                  avatar={choice}
                  name={`${t("userAvatar")} ${index + 1}`}
                  size="md"
                />
                <span className="sr-only">{`${t("userAvatar")} ${index + 1}`}</span>
              </label>
            ))}
          </fieldset>
        </section>

        <form
          className={`${PANEL} pl-8 max-[640px]:mt-6 max-[640px]:border-0 max-[640px]:border-t max-[640px]:border-solid max-[640px]:border-[#E9DAA9] max-[640px]:pt-6 max-[640px]:pl-0`}
          onSubmit={(event) => void savePassword(event)}
        >
          <h3 className={HEADING}>{t("changePassword")}</h3>
          <label className={LABEL}>
            <span>{t("currentPassword")}</span>
            <span className="relative block">
              {wrongCurrent ? <StickerBadge n={1} /> : null}
              <input
                aria-invalid={wrongCurrent || undefined}
                className={`${FIELD} aria-invalid:border-err! aria-invalid:shadow-[0_0_0_3px_#FFE4E4,3px_3px_0_#EF4444]!`}
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                minLength={5}
                maxLength={128}
                required
                disabled={busy !== null}
                onChange={(event) => setCurrentPassword(event.target.value)}
              />
            </span>
          </label>
          <label className={LABEL}>
            <span>{t("newPassword")}</span>
            <input
              className={FIELD}
              type="password"
              autoComplete="new-password"
              value={newPassword}
              minLength={5}
              maxLength={128}
              required
              disabled={busy !== null}
              onChange={(event) => setNewPassword(event.target.value)}
            />
          </label>
          <label className={LABEL}>
            <span>{t("registerConfirmPassword")}</span>
            <span className="relative block">
              {mismatch ? <StickerBadge n={1} /> : null}
              <input
                aria-invalid={mismatch || undefined}
                aria-describedby={mismatch ? "password-field-error" : undefined}
                className={`${FIELD} aria-invalid:border-err! aria-invalid:shadow-[0_0_0_3px_#FFE4E4,3px_3px_0_#EF4444]!`}
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                minLength={5}
                maxLength={128}
                required
                disabled={busy !== null}
                onChange={(event) => setConfirmPassword(event.target.value)}
              />
            </span>
          </label>
          <div className="flex min-h-[30px] items-center gap-3">
            <button
              className={`primary-action ${PRESS}`}
              type="submit"
              disabled={busy !== null}
              aria-busy={busy === "password" || undefined}
            >
              {busy === "password" ? (
                <span className="spinner" aria-hidden="true" />
              ) : null}
              {t("save")}
            </button>
            {saved === "password" ? (
              <span className={SAVED} role="status">
                {t("saved")}
              </span>
            ) : null}
          </div>
        </form>
      </div>
    </SectionCard>
  );
}
