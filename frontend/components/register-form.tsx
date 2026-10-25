"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { useRouter } from "next/navigation";

import { DismissibleAlert } from "./dismissible-alert";
import { type RegistrationOptions } from "../lib/api";
import { localizeError, type MessageKey } from "../lib/i18n";
import { sanitizeNextPath } from "../lib/navigation";
import { markTourPending } from "../lib/onboarding";
import { useSetAcademyMood } from "./academy/mood";
import { useT } from "../lib/i18n";
import { useSession } from "./session-provider";

/** Suggestions are display hints; the server owns canonical group identity. */
function foldGroupName(value: string) {
  return value.normalize("NFKC").trim().replace(/\s+/gu, " ").toLowerCase();
}

const TOTAL_STEPS = 2;
const GROUP_LIST_ID = "register-group-listbox";

function groupOptionId(index: number) {
  return `register-group-option-${index}`;
}

/** Mirrors PASSWORD_MIN in the backend registration service. */
const PASSWORD_MIN = 5;

export function RegisterForm({ onCancel }: { onCancel?: () => void }) {
  const t = useT();
  const router = useRouter();
  const { api, register } = useSession();
  const [step, setStep] = useState<1 | 2>(1);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [localError, setLocalError] = useState<MessageKey | null>(null);
  // Bumped on every submit, so a closed message shows again on a repeat.
  const [attempt, setAttempt] = useState(0);
  const [groupName, setGroupName] = useState("");
  const [options, setOptions] = useState<RegistrationOptions | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [listOpen, setListOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const listRef = useRef<HTMLUListElement | null>(null);
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

  // Nothing is offered until something is typed: an untouched field that drops
  // the whole course on the reader is answering a question they have not asked
  // yet, and it buries the one name they came here to write.  A substring
  // match rather than a prefix match, so a student who remembers only part of
  // the name their group used still finds it.
  const suggestions = useMemo(() => {
    const query = foldGroupName(groupName);
    if (!query) return [];
    return groups.filter((group) => foldGroupName(group.name).includes(query));
  }, [groups, groupName]);

  useEffect(() => {
    if (activeIndex < 0) return;
    // Optional because not every DOM implementation has it, and a highlight
    // that cannot be scrolled to is still the right highlight.
    listRef.current?.children.item(activeIndex)?.scrollIntoView?.({
      block: "nearest",
    });
  }, [activeIndex]);

  const exactMatch = useMemo(() => {
    const typed = foldGroupName(groupName);
    if (!typed) return null;
    return groups.find((group) => foldGroupName(group.name) === typed) ?? null;
  }, [groups, groupName]);

  const showGroupList = listOpen && suggestions.length > 0;

  const requestedNext =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("next")
      : null;
  const nextPath = sanitizeNextPath(requestedNext);

  function chooseGroup(name: string) {
    setGroupName(name);
    setListOpen(false);
    setActiveIndex(-1);
  }

  function onGroupKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (suggestions.length === 0) return;
      // Arrows drive the list, so they must not also run the browser's
      // caret-to-end behaviour underneath it.
      event.preventDefault();
      const last = suggestions.length - 1;
      if (!listOpen) {
        setListOpen(true);
        setActiveIndex(event.key === "ArrowDown" ? 0 : last);
        return;
      }
      const next = activeIndex + (event.key === "ArrowDown" ? 1 : -1);
      setActiveIndex(next > last ? 0 : next < 0 ? last : next);
      return;
    }
    if (event.key === "Enter" && listOpen && activeIndex >= 0) {
      // A highlighted row is the answer to this step. Submitting whatever was
      // half-typed underneath it would create a group by accident.
      event.preventDefault();
      chooseGroup(suggestions[activeIndex].name);
      return;
    }
    if (event.key === "Escape" && listOpen) {
      event.preventDefault();
      setListOpen(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAttempt((value) => value + 1);
    // The group step is the last one; the first only advances the form.
    if (step === 1) {
      // Checked here rather than through the server so the student is told
      // about a short or mistyped password before they pick a group.
      if (password.length < PASSWORD_MIN) {
        setLocalError("passwordTooShort");
        return;
      }
      if (password !== confirmation) {
        setLocalError("registerPasswordMismatch");
        return;
      }
      setLocalError(null);
      setStep(2);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // No display name is collected: the server falls back to the username,
      // which is what a classroom roster shows anyway.
      const session = await register({
        username: username.trim(),
        password,
        group_name: groupName,
        ...(options ? { course_id: options.course_id } : {}),
      });
      // A new account is shown round its home once, on arrival.
      markTourPending(session.user.id);
      router.replace(nextPath || "/student");
    } catch (cause) {
      // A lost username race only returns to the account step; the session stays intact.
      if (
        cause &&
        typeof cause === "object" &&
        "code" in cause &&
        cause.code === "username_taken"
      ) {
        setStep(1);
      }
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
      {localError ? (
        <DismissibleAlert
          className="form-error"
          resetKey={`${attempt}:${localError}`}
        >
          {t(localError)}
        </DismissibleAlert>
      ) : error ? (
        <DismissibleAlert className="form-error" resetKey={error}>
          {localizeError(error, "registerFailed")}
        </DismissibleAlert>
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
                aria-describedby="register-password-rule"
                autoComplete="new-password"
                type="password"
                value={password}
                minLength={PASSWORD_MIN}
                maxLength={128}
                onChange={(event) => setPassword(event.target.value)}
                onFocus={() => setMood("discreet")}
                onBlur={() => setMood("idle")}
                required
              />
            </label>
            <small className="muted" id="register-password-rule">
              {t("passwordRule")}
            </small>
            <label>
              <span>{t("registerConfirmPassword")}</span>
              <input
                autoComplete="new-password"
                type="password"
                value={confirmation}
                maxLength={128}
                onChange={(event) => setConfirmation(event.target.value)}
                onFocus={() => setMood("discreet")}
                onBlur={() => setMood("idle")}
                required
              />
            </label>
            <button className="primary-action" type="submit" disabled={busy}>
              {t("registerNext")}
            </button>
            {onCancel ? (
              <p className="academy-switch">
                {t("haveAccount")}{" "}
                <button
                  className="academy-textlink"
                  type="button"
                  disabled={busy}
                  onClick={onCancel}
                >
                  {t("signIn")}
                </button>
              </p>
            ) : null}
          </>
        ) : (
          <>
            {/* A typed field with a list under it rather than a wall of
                chips: the reader looks for one name among many, and the list
                floats so growing it never moves the button below. */}
            <div className="academy-combo">
              <label htmlFor="register-group-input">
                <span>{t("registerGroupLabel")}</span>
              </label>
              <div className="academy-combo-field">
                <input
                  id="register-group-input"
                  role="combobox"
                  aria-expanded={showGroupList}
                  aria-controls={GROUP_LIST_ID}
                  aria-autocomplete="list"
                  aria-activedescendant={
                    showGroupList && activeIndex >= 0
                      ? groupOptionId(activeIndex)
                      : undefined
                  }
                  autoComplete="off"
                  value={groupName}
                  maxLength={200}
                  onChange={(event) => {
                    setGroupName(event.target.value);
                    setListOpen(true);
                    // Typing narrows the list, so the highlight belongs to the
                    // list as it stands now rather than to whichever row
                    // happened to be sitting under it.
                    setActiveIndex(-1);
                  }}
                  onKeyDown={onGroupKeyDown}
                  onFocus={() => {
                    setMood("attentive");
                    setListOpen(true);
                  }}
                  onBlur={() => {
                    setMood("idle");
                    setListOpen(false);
                  }}
                  autoFocus
                  required
                />
                {showGroupList ? (
                  <ul
                    className="academy-combo-list"
                    id={GROUP_LIST_ID}
                    ref={listRef}
                    role="listbox"
                    aria-label={t("registerSuggestions")}
                    // Keeps the field focused through the click, so choosing a
                    // row does not blur the list out from under the pointer.
                    onMouseDown={(event) => event.preventDefault()}
                  >
                    {suggestions.map((group, index) => (
                      <li
                        className={
                          index === activeIndex
                            ? "academy-combo-option is-active"
                            : "academy-combo-option"
                        }
                        key={group.name}
                        id={groupOptionId(index)}
                        role="option"
                        aria-selected={index === activeIndex}
                        onMouseEnter={() => setActiveIndex(index)}
                        onClick={() => chooseGroup(group.name)}
                      >
                        <span>{group.name}</span>
                        <small>
                          {t("memberCountShort", { count: group.member_count })}
                        </small>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
              {groupName.trim() ? (
                <p className="academy-combo-verdict" role="status">
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
