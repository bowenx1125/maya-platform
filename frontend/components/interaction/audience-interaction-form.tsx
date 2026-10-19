"use client";

import { useEffect, useRef, useState } from "react";

import { DismissibleAlert } from "../dismissible-alert";
import { apiErrorMessage, PlatformApiError } from "../../lib/api";
import { useLocale } from "../locale";
import {
  audienceId,
  isBusyRefusal,
  isRateLimited,
  nextFormPollDelay,
  retryAfterMs,
  sleep,
  SUBMIT_RETRY_ATTEMPTS,
  submitRetryDelay,
  FORM_POLL_MIN_MS,
} from "./audience-backoff";
import type { AudienceInteractionApi } from "./types";
import appearance from "../workspace-appearance.module.css";
import styles from "./audience-interaction-form.module.css";

type AudienceInteractionFormProps = {
  accessToken: string;
  api?: AudienceInteractionApi;
};

function newSubmissionId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.getRandomValues === "function"
  ) {
    crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

function collectionFinalized(cause: unknown): boolean {
  return (
    cause instanceof PlatformApiError && cause.code === "interaction_finalized"
  );
}

const browserAudienceApi: AudienceInteractionApi = {
  getForm: (accessToken) =>
    requestBrowser(
      `/classroom-interactions/${encodeURIComponent(accessToken)}`,
    ),
  submitVote: (accessToken, payload) =>
    requestBrowser(
      `/classroom-interactions/${encodeURIComponent(accessToken)}/votes`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Maya-Audience": audienceId(),
        },
        body: JSON.stringify(payload),
      },
    ),
  submitBarrage: (accessToken, payload) =>
    requestBrowser(
      `/classroom-interactions/${encodeURIComponent(accessToken)}/barrages`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Maya-Audience": audienceId(),
        },
        body: JSON.stringify(payload),
      },
    ),
};

async function requestBrowser<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    cache: "no-store",
    credentials: "omit",
    referrerPolicy: "no-referrer",
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const payload: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    const message =
      payload && typeof payload === "object" && "message" in payload
        ? String((payload as { message?: unknown }).message ?? "Request failed")
        : "Request failed";
    const code =
      payload &&
      typeof payload === "object" &&
      "code" in payload &&
      typeof payload.code === "string"
        ? payload.code
        : undefined;
    const details: Record<string, unknown> =
      payload &&
      typeof payload === "object" &&
      "details" in payload &&
      payload.details &&
      typeof payload.details === "object"
        ? { ...(payload.details as Record<string, unknown>) }
        : {};
    // A busy server says how long to wait; the header counts too.
    const header = Number(response.headers?.get?.("Retry-After"));
    if (details.retry_after_seconds === undefined && header > 0) {
      details.retry_after_seconds = header;
    }
    throw new PlatformApiError(response.status, message, { code, details });
  }
  return payload as T;
}

export function AudienceInteractionForm({
  accessToken,
  api = browserAudienceApi,
}: AudienceInteractionFormProps) {
  const { t } = useLocale();
  const messageInput = useRef<HTMLTextAreaElement>(null);
  const [form, setForm] = useState<Awaited<
    ReturnType<AudienceInteractionApi["getForm"]>
  > | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [syncFailed, setSyncFailed] = useState(false);
  const [nickname, setNickname] = useState("");
  const [selectedParticipant, setSelectedParticipant] = useState("");
  const [voteState, setVoteState] = useState<"idle" | "busy" | "success">(
    "idle",
  );
  const [barrageState, setBarrageState] = useState<"idle" | "busy" | "success">(
    "idle",
  );
  const [barrageText, setBarrageText] = useState("");
  const [voteError, setVoteError] = useState<unknown>(null);
  const [barrageError, setBarrageError] = useState<unknown>(null);
  const [votePayload, setVotePayload] = useState<{
    participant_id: string;
    client_submission_id: string;
  } | null>(null);
  const [barragePayload, setBarragePayload] = useState<{
    nickname: string;
    raw_text: string;
    turn_id?: string;
    client_submission_id: string;
  } | null>(null);
  // Conclude finalizes the window. Treating that as a disconnect would leave
  // Vote and Send enabled for another rejected attempt.
  const [submissionsClosed, setSubmissionsClosed] = useState(false);
  const submissionsClosedRef = useRef(false);
  // A 503 is resent (same client_submission_id) while this says so.
  const [voteRetrying, setVoteRetrying] = useState(false);
  const [barrageRetrying, setBarrageRetrying] = useState(false);
  const [barrageWaitSeconds, setBarrageWaitSeconds] = useState(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  /** Send once, then resend after a 503 with the same payload, backing off. */
  async function sendWithRetry<T>(
    send: () => Promise<T>,
    setRetrying: (value: boolean) => void,
  ): Promise<T> {
    for (let attempt = 0; ; attempt += 1) {
      try {
        const result = await send();
        if (mounted.current) setRetrying(false);
        return result;
      } catch (cause) {
        if (
          !isBusyRefusal(cause) ||
          attempt + 1 >= SUBMIT_RETRY_ATTEMPTS ||
          !mounted.current
        ) {
          if (mounted.current) setRetrying(false);
          throw cause;
        }
        setRetrying(true);
        await sleep(submitRetryDelay(attempt, cause));
      }
    }
  }

  function lockFinalizedCollection() {
    submissionsClosedRef.current = true;
    setSubmissionsClosed(true);
    setSyncFailed(false);
    setForm((current) =>
      current ? { ...current, barrage_open: false } : current,
    );
  }

  useEffect(() => {
    let active = true;
    void api
      .getForm(accessToken)
      .then((result) => {
        if (!active) return;
        setLoadError(null);
        setForm(result);
        setSelectedParticipant(result.participants[0]?.participant_id ?? "");
      })
      .catch((cause: unknown) => {
        if (active) setLoadError(cause);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [accessToken, api]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    // 2 s while the server answers; backs off to 10 s (or its Retry-After)
    // while it is busy or unreachable.
    let delay = FORM_POLL_MIN_MS;
    async function refreshTurn() {
      let failure: unknown = null;
      try {
        const next = await api.getForm(accessToken);
        // A stale open form must not undo Conclude. A finalized window cannot
        // reopen, so the lock stays until this page is left.
        if (active && !submissionsClosedRef.current) {
          setForm(next);
          setSyncFailed(false);
        }
      } catch (cause: unknown) {
        if (!active) return;
        if (collectionFinalized(cause)) {
          // An authoritative answer, not a busy server: keep the pace.
          lockFinalizedCollection();
          return;
        }
        failure = cause;
        if (!submissionsClosedRef.current) setSyncFailed(true);
      } finally {
        if (active) {
          delay = nextFormPollDelay(delay, failure);
          timer = setTimeout(() => void refreshTurn(), delay);
        }
      }
    }
    timer = setTimeout(() => void refreshTurn(), delay);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [accessToken, api]);

  if (loading) {
    return (
      <main className={`${appearance.appearance} ${styles.audiencePage}`}>
        <p role="status">{t("audienceLoading")}</p>
      </main>
    );
  }
  if (loadError || !form) {
    return (
      <main className={`${appearance.appearance} ${styles.audiencePage}`}>
        <section className={styles.audienceCard} role="alert">
          <span className={styles.eyebrow}>{t("appName")}</span>
          <h1>{t("audienceUnavailable")}</h1>
          <p>{apiErrorMessage(loadError, t("audienceUnavailableHint"))}</p>
        </section>
      </main>
    );
  }

  const canInteract = nickname.trim().length > 0;
  const turnBound = Boolean(form.current_turn_id);
  async function submitVote() {
    if (
      !canInteract ||
      !selectedParticipant ||
      voteState !== "idle" ||
      submissionsClosedRef.current
    )
      return;
    setVoteState("busy");
    setVoteError(null);
    try {
      const payload = votePayload ?? {
        participant_id: selectedParticipant,
        client_submission_id: newSubmissionId(),
      };
      if (!votePayload) setVotePayload(payload);
      await sendWithRetry(
        () => api.submitVote(accessToken, payload),
        setVoteRetrying,
      );
      if (!mounted.current) return;
      setVoteState("success");
    } catch (cause) {
      if (!mounted.current) return;
      setVoteState("idle");
      setVoteError(cause);
      if (collectionFinalized(cause)) lockFinalizedCollection();
    }
  }

  async function submitBarrage() {
    if (
      !canInteract ||
      !barrageText.trim() ||
      barrageState === "busy" ||
      syncFailed ||
      submissionsClosedRef.current ||
      form?.barrage_open === false
    )
      return;
    setBarrageState("busy");
    setBarrageError(null);
    setBarrageWaitSeconds(0);
    try {
      const payload = barragePayload ?? {
        nickname,
        raw_text: barrageText,
        ...(form?.current_turn_id ? { turn_id: form.current_turn_id } : {}),
        client_submission_id: newSubmissionId(),
      };
      if (!barragePayload) setBarragePayload(payload);
      await sendWithRetry(
        () => api.submitBarrage(accessToken, payload),
        setBarrageRetrying,
      );
      if (!mounted.current) return;
      setBarrageState("success");
      setBarrageText("");
      setBarragePayload(null);
    } catch (cause) {
      if (!mounted.current) return;
      setBarrageState("idle");
      if (isRateLimited(cause)) {
        // Too fast: say how long to wait; nothing is resent behind the
        // student, and the text stays for them to send again.
        setBarrageWaitSeconds(
          Math.max(1, Math.ceil(retryAfterMs(cause) / 1000)),
        );
        return;
      }
      setBarrageError(cause);
      if (
        cause instanceof PlatformApiError &&
        cause.code === "barrage_turn_changed"
      ) {
        setBarragePayload(null);
        try {
          setForm(await api.getForm(accessToken));
          setSyncFailed(false);
        } catch {
          setSyncFailed(true);
        }
      } else if (
        cause instanceof PlatformApiError &&
        cause.code === "barrage_collection_closed"
      ) {
        setForm((current) =>
          current ? { ...current, barrage_open: false } : current,
        );
      } else if (collectionFinalized(cause)) {
        lockFinalizedCollection();
      }
    }
  }

  return (
    <main className={`${appearance.appearance} ${styles.audiencePage}`}>
      <section className={styles.audienceCard}>
        <header className={styles.header}>
          <span className={styles.eyebrow}>{t("audienceEyebrow")}</span>
          <h1>{form.topic}</h1>
        </header>

        <label className={styles.field}>
          <span>{t("audienceNickname")}</span>
          <input
            value={nickname}
            onChange={(event) => setNickname(event.target.value)}
            autoComplete="nickname"
            enterKeyHint="next"
            placeholder={t("audienceNicknamePlaceholder")}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                event.preventDefault();
                messageInput.current?.focus();
              }
            }}
            disabled={barragePayload !== null}
          />
        </label>

        {canInteract ? (
          <div className={styles.audienceSections}>
            <form
              className={`${styles.audienceSection} ${styles.messageSection}`}
              onSubmit={(event) => {
                event.preventDefault();
                void submitBarrage();
              }}
              aria-label={t("audienceBarrage")}
            >
              <div className={styles.sectionHeading}>
                <h2>{t("audienceBarrage")}</h2>
                {barrageState === "success" ? (
                  <strong role="status">{t("audienceBarrageSubmitted")}</strong>
                ) : null}
              </div>
              {form.round_no ? (
                <span className={styles.round}>
                  {t("audienceRound")} {form.round_no}
                </span>
              ) : null}
              {form.barrage_open === false ? (
                <p className={styles.closed} role="status">
                  {t("audienceCollectionClosed")}
                </p>
              ) : null}
              {syncFailed ? (
                <p className={styles.connection} role="status">
                  {t("audienceReconnecting")}
                </p>
              ) : null}
              {barrageRetrying ? (
                <p className={styles.connection} role="status">
                  {t("audienceBusyRetrying")}
                </p>
              ) : null}
              {barrageWaitSeconds > 0 ? (
                <p className={styles.connection} role="status">
                  {t("audienceTooFast", { seconds: barrageWaitSeconds })}
                </p>
              ) : null}
              <textarea
                ref={messageInput}
                aria-label={t("audienceBarrage")}
                aria-invalid={barrageError ? true : undefined}
                aria-describedby={
                  [
                    turnBound ? "message-count" : "",
                    barrageError ? "message-error" : "",
                  ]
                    .filter(Boolean)
                    .join(" ") || undefined
                }
                placeholder={t("audienceBarragePlaceholder")}
                value={barrageText}
                onChange={(event) => {
                  setBarrageText(event.target.value);
                  setBarrageError(null);
                  setBarragePayload(null);
                  setBarrageState("idle");
                  setBarrageWaitSeconds(0);
                }}
                maxLength={turnBound ? 300 : undefined}
                rows={5}
                disabled={
                  !canInteract ||
                  submissionsClosed ||
                  form.barrage_open === false ||
                  barrageState === "busy"
                }
              />
              <div className={styles.sendRow}>
                {turnBound ? (
                  <span id="message-count" className={styles.characterCount}>
                    {barrageText.length} / 300
                  </span>
                ) : null}
                <button
                  className={styles.primaryButton}
                  type="submit"
                  disabled={
                    !canInteract ||
                    syncFailed ||
                    submissionsClosed ||
                    !barrageText.trim() ||
                    form.barrage_open === false ||
                    barrageState === "busy"
                  }
                >
                  {barrageState === "busy"
                    ? t("audienceSending")
                    : t("audienceBarrageSend")}
                </button>
              </div>
              {barrageError ? (
                <DismissibleAlert
                  id="message-error"
                  className={styles.error}
                  resetKey={barrageError}
                >
                  {apiErrorMessage(barrageError)}
                </DismissibleAlert>
              ) : null}
            </form>
            <form
              className={`${styles.audienceSection} ${styles.voteSection}`}
              onSubmit={(event) => {
                event.preventDefault();
                void submitVote();
              }}
              aria-label={t("audienceVote")}
            >
              <div className={styles.sectionHeading}>
                <h2>{t("audienceVote")}</h2>
                {voteState === "success" ? (
                  <strong role="status">{t("audienceVoteSubmitted")}</strong>
                ) : null}
              </div>

              <div
                className={styles.participantChoices}
                role="radiogroup"
                aria-label={t("audienceVote")}
              >
                {form.participants.map((participant) => (
                  <label
                    className={styles.choice}
                    key={participant.participant_id}
                  >
                    <input
                      type="radio"
                      name="participant"
                      value={participant.participant_id}
                      checked={
                        selectedParticipant === participant.participant_id
                      }
                      onChange={(event) =>
                        setSelectedParticipant(event.target.value)
                      }
                      disabled={
                        !canInteract ||
                        submissionsClosed ||
                        voteState !== "idle" ||
                        votePayload !== null
                      }
                    />
                    <span>
                      <b>{participant.slot}</b> {participant.name}
                    </span>
                  </label>
                ))}
              </div>
              <button
                className={styles.secondaryButton}
                type="submit"
                disabled={
                  !canInteract || submissionsClosed || voteState !== "idle"
                }
              >
                {voteState === "busy"
                  ? t("audienceSubmitting")
                  : t("audienceVoteSubmit")}
              </button>
              {voteRetrying ? (
                <p className={styles.connection} role="status">
                  {t("audienceBusyRetrying")}
                </p>
              ) : null}
              {voteError ? (
                <DismissibleAlert className={styles.error} resetKey={voteError}>
                  {apiErrorMessage(voteError)}
                </DismissibleAlert>
              ) : null}
            </form>
          </div>
        ) : null}
      </section>
    </main>
  );
}
