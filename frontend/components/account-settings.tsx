"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { cachedCall, requestCacheIdentity } from "../lib/request-cache";
import { useT } from "../lib/i18n";
import { useSession } from "./session-provider";
import { ErrorNotice, SectionCard } from "./ui";
import { USER_AVATAR_CHOICES, UserAvatar } from "./user-avatar";

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
    "avatar" | "name" | "group" | "password" | null
  >(null);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState<
    "avatar" | "name" | "group" | "password" | null
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
    if (!studentCourseIds || !currentGroupId) return;
    let active = true;
    // The group is the page's own read too (shared cache, same key).
    void Promise.all([
      api.registrationOptions(),
      cachedCall(
        api,
        requestCacheIdentity(user?.id, identityGeneration),
        "group",
        [currentGroupId],
        () => api.group(currentGroupId),
      ),
    ])
      .then(([options, group]) => {
        if (!active) return;
        // The choices are the course's existing groups; the picker never
        // offers to start a new one.
        const names = studentCourseIds.split(",").includes(options.course_id)
          ? options.groups
              .map((choice) => choice.name)
              .sort((left, right) =>
                left.localeCompare(right, undefined, {
                  numeric: true,
                  sensitivity: "base",
                }),
              )
          : [];
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
  }, [api, currentGroupId, identityGeneration, studentCourseIds, user?.id]);
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
    if (newPassword !== confirmPassword) {
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

  if (!user) return null;

  return (
    <SectionCard title={t("profile")} className="account-settings-card">
      {error ? <ErrorNotice error={error} /> : null}
      <div className="account-settings-grid">
        <section className="profile-panel" aria-labelledby="profile-avatar">
          <div className="profile-panel-heading">
            <UserAvatar
              avatar={avatar}
              name={user.display_name}
              userId={user.id}
              size="lg"
            />
            <div>
              <h3 id="profile-avatar">{t("userAvatar")}</h3>
              <span>{user.display_name}</span>
            </div>
            {saved === "avatar" ? (
              <span className="profile-saved" role="status">
                {t("saved")}
              </span>
            ) : null}
          </div>
          <form
            className="profile-name"
            onSubmit={(event) => void saveName(event)}
          >
            <label>
              <span>{t("displayNameLabel")}</span>
              <input
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
                className="primary-action"
                type="submit"
                disabled={busy !== null}
              >
                {t("save")}
              </button>
            ) : saved === "name" ? (
              <span className="profile-saved" role="status">
                {t("saved")}
              </span>
            ) : null}
          </form>
          {groupNames.length > 1 ? (
            <form
              className="profile-name"
              onSubmit={(event) => void saveGroup(event)}
            >
              <label>
                <span>{t("groupNameLabel")}</span>
                <select
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
                  className="primary-action"
                  type="submit"
                  disabled={busy !== null}
                >
                  {t("save")}
                </button>
              ) : saved === "group" ? (
                <span className="profile-saved" role="status">
                  {t("saved")}
                </span>
              ) : null}
            </form>
          ) : null}
          <fieldset className="avatar-picker" disabled={busy !== null}>
            <legend className="sr-only">{t("userAvatar")}</legend>
            {USER_AVATAR_CHOICES.map((choice, index) => (
              <label
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
          className="profile-panel password-panel"
          onSubmit={(event) => void savePassword(event)}
        >
          <h3>{t("changePassword")}</h3>
          <label>
            <span>{t("currentPassword")}</span>
            <input
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              minLength={5}
              maxLength={128}
              required
              disabled={busy !== null}
              onChange={(event) => setCurrentPassword(event.target.value)}
            />
          </label>
          <label>
            <span>{t("newPassword")}</span>
            <input
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
          <label>
            <span>{t("registerConfirmPassword")}</span>
            <input
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              minLength={5}
              maxLength={128}
              required
              disabled={busy !== null}
              onChange={(event) => setConfirmPassword(event.target.value)}
            />
          </label>
          <div className="profile-action-row">
            <button
              className="primary-action"
              type="submit"
              disabled={busy !== null}
            >
              {t("save")}
            </button>
            {saved === "password" ? (
              <span className="profile-saved" role="status">
                {t("saved")}
              </span>
            ) : null}
          </div>
        </form>
      </div>
    </SectionCard>
  );
}
