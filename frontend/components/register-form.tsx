"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { type RegistrationOptions } from "../lib/api";
import { localizeError } from "../lib/i18n";
import { sanitizeNextPath } from "../lib/navigation";
import { useSetAcademyMood } from "./academy/mood";
import { useLocale, useT } from "./locale";
import { useSession } from "./session-provider";

/** Collapse case and whitespace the way the server does before matching. */
function foldGroupName(value: string) {
  return value.trim().replace(/\s+/gu, " ").toLocaleLowerCase();
}

const TOTAL_STEPS = 2;

export function RegisterForm({ onCancel }: { onCancel?: () => void }) {
  const t = useT();
  const { locale } = useLocale();
  const router = useRouter();
  const { api, register } = useSession();
  const [step, setStep] = useState<1 | 2>(1);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [groupName, setGroupName] = useState("");
  const [options, setOptions] = useState<RegistrationOptions | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const setMood = useSetAcademyMood();

  useEffect(() => {
    if (!error) return;
    setMood("refused");
    const timer = window.setTimeout(() => setMood("idle"), 900);
    return () => window.clearTimeout(timer);
  }, [error, setMood]);

  useEffect(() => {
    let active = true;
    void api
      .registrationOptions()
      .then((next) => {
        if (active) setOptions(next);
      })
      .catch(() => {
        // The form still works without suggestions: a typed name either joins
        // an existing group or creates one, and the server decides which.
        if (active) setOptions(null);
      });
    return () => {
      active = false;
    };
  }, [api]);

  const groups = useMemo(() => options?.groups ?? [], [options]);

  // A substring match rather than a prefix match: a student who remembers only
  // part of the name their group used still finds it.
  const suggestions = useMemo(() => {
    const query = foldGroupName(groupName);
    if (!query) return groups;
    return groups.filter((group) => foldGroupName(group.name).includes(query));
  }, [groups, groupName]);

  const exactMatch = useMemo(() => {
    const typed = foldGroupName(groupName);
    if (!typed) return null;
    return groups.find((group) => foldGroupName(group.name) === typed) ?? null;
  }, [groups, groupName]);

  const requestedNext =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("next")
      : null;
  const nextPath = sanitizeNextPath(requestedNext);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // The group step is the last one; the first only advances the form.
    if (step === 1) {
      setStep(2);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // No display name is collected: the server falls back to the username,
      // which is what a classroom roster shows anyway.
      await register({
        username: username.trim(),
        password,
        group_name: groupName,
        ...(options ? { course_id: options.course_id } : {}),
      });
      router.replace(nextPath || "/student");
    } catch (cause) {
      setError(cause);
      // A rejected username belongs to the first step, so send the student
      // back to the field they can actually correct.
      setStep(1);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="login-panel" aria-labelledby="register-title">
      <h2 id="register-title">{t("registerTitle")}</h2>
      <p className="academy-step" aria-live="polite">
        {t("registerStepOf", { current: step, total: TOTAL_STEPS })} ·{" "}
        {step === 1 ? t("registerStepAccount") : t("registerStepGroup")}
      </p>
      {error ? (
        <p className="form-error" role="alert">
          {localizeError(error, locale, "registerFailed")}
        </p>
      ) : null}
      <form className="stack-form login-form" onSubmit={submit}>
        {step === 1 ? (
          <>
            <label>
              <span>{t("username")}</span>
              <input
                autoComplete="username"
                value={username}
                maxLength={64}
                onChange={(event) => setUsername(event.target.value)}
                onFocus={() => setMood("attentive")}
                onBlur={() => setMood("idle")}
                required
              />
            </label>
            <label>
              <span>{t("password")}</span>
              <input
                autoComplete="new-password"
                type="password"
                value={password}
                maxLength={128}
                onChange={(event) => setPassword(event.target.value)}
                onFocus={() => setMood("discreet")}
                onBlur={() => setMood("idle")}
                required
              />
            </label>
            <button className="primary-action" type="submit" disabled={busy}>
              {t("registerNext")}
            </button>
            {onCancel ? (
              <button
                className="secondary-action"
                type="button"
                disabled={busy}
                onClick={onCancel}
              >
                {t("haveAccount")} {t("signIn")}
              </button>
            ) : null}
          </>
        ) : (
          <>
            <label>
              <span>{t("registerGroupLabel")}</span>
              <input
                aria-describedby="register-group-hint"
                value={groupName}
                maxLength={200}
                onChange={(event) => setGroupName(event.target.value)}
                onFocus={() => setMood("attentive")}
                onBlur={() => setMood("idle")}
                autoFocus
                required
              />
            </label>
            <small className="muted" id="register-group-hint">
              {t("registerGroupHint")}
            </small>

            {/* The suggestions and the verdict live on a step of their own, so
                growing this list cannot push the rest of the form around. */}
            <div className="academy-suggestions">
              {suggestions.length > 0 ? (
                <div
                  className="quick-switch"
                  aria-label={t("registerSuggestions")}
                >
                  <span className="section-label">
                    {t("registerSuggestions")}
                  </span>
                  <div className="chip-row">
                    {suggestions.map((group) => (
                      <button
                        className="chip-button"
                        key={group.name}
                        type="button"
                        disabled={busy}
                        onClick={() => setGroupName(group.name)}
                      >
                        {group.name} ·{" "}
                        {t("memberCountShort", { count: group.member_count })}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              {groupName.trim() ? (
                <p className="muted" role="status">
                  {exactMatch
                    ? t("registerWillJoin", {
                        name: exactMatch.name,
                        count: exactMatch.member_count,
                      })
                    : t("registerWillCreate")}
                </p>
              ) : null}
            </div>

            <button className="primary-action" type="submit" disabled={busy}>
              {busy ? t("registering") : t("registerSubmit")}
            </button>
            <button
              className="secondary-action"
              type="button"
              disabled={busy}
              onClick={() => setStep(1)}
            >
              {t("registerBack")}
            </button>
          </>
        )}
      </form>
    </section>
  );
}
