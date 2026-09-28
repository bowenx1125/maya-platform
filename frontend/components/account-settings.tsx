"use client";

import { useState } from "react";
import type { FormEvent } from "react";

import { useT } from "./locale";
import { useSession } from "./session-provider";
import { ErrorNotice, SectionCard } from "./ui";
import { USER_AVATAR_CHOICES, UserAvatar } from "./user-avatar";

export function AccountSettings() {
  const t = useT();
  const { api, refresh, user } = useSession();
  const [avatar, setAvatar] = useState<string | null>(user?.avatar ?? null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState<"avatar" | "password" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState<"avatar" | "password" | null>(null);

  async function saveAvatar(event: FormEvent) {
    event.preventDefault();
    setBusy("avatar");
    setSaved(null);
    setError(null);
    try {
      await api.updateCurrentUser(avatar);
      await refresh();
      setSaved("avatar");
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
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
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setSaved("password");
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
    }
  }

  if (!user) return null;

  return (
    <SectionCard title={t("profile")} className="account-settings-card">
      {error ? <ErrorNotice error={error} /> : null}
      <div className="account-settings-grid">
        <form
          className="profile-panel"
          onSubmit={(event) => void saveAvatar(event)}
        >
          <div className="profile-panel-heading">
            <UserAvatar
              avatar={avatar}
              name={user.display_name}
              userId={user.id}
              size="lg"
            />
            <div>
              <h3>{t("userAvatar")}</h3>
              <span>{user.display_name}</span>
            </div>
          </div>
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
                  onChange={() => setAvatar(choice)}
                />
                <UserAvatar
                  avatar={choice}
                  name={`${t("userAvatar")} ${index + 1}`}
                  size="sm"
                />
                <span className="sr-only">{`${t("userAvatar")} ${index + 1}`}</span>
              </label>
            ))}
          </fieldset>
          <div className="profile-action-row">
            <button
              className="inline-button"
              type="submit"
              disabled={busy !== null}
            >
              {t("save")}
            </button>
            {saved === "avatar" ? (
              <span role="status">{t("saved")}</span>
            ) : null}
          </div>
        </form>

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
              className="inline-button"
              type="submit"
              disabled={busy !== null}
            >
              {t("save")}
            </button>
            {saved === "password" ? (
              <span role="status">{t("saved")}</span>
            ) : null}
          </div>
        </form>
      </div>
    </SectionCard>
  );
}
