"use client";

import { useEffect, useState } from "react";

import { apiErrorMessage } from "../../lib/api";
import { LanguageSwitcher, useLocale } from "../locale";
import type { AudienceInteractionApi } from "./types";
import styles from "./interaction.module.css";

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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  submitBarrage: (accessToken, payload) =>
    requestBrowser(
      `/classroom-interactions/${encodeURIComponent(accessToken)}/barrages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
    throw new Error(message);
  }
  return payload as T;
}

export function AudienceInteractionForm({
  accessToken,
  api = browserAudienceApi,
}: AudienceInteractionFormProps) {
  const { t } = useLocale();
  const [form, setForm] = useState<Awaited<
    ReturnType<AudienceInteractionApi["getForm"]>
  > | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
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
    client_submission_id: string;
  } | null>(null);

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

  if (loading) {
    return (
      <main className={styles.audiencePage}>
        <LanguageSwitcher />
        <p role="status">{t("audienceLoading")}</p>
      </main>
    );
  }
  if (loadError || !form) {
    return (
      <main className={styles.audiencePage}>
        <LanguageSwitcher />
        <section className={styles.audienceCard} role="alert">
          <span className={styles.eyebrow}>{t("appName")}</span>
          <h1>{t("audienceUnavailable")}</h1>
          <p>{apiErrorMessage(loadError, t("audienceUnavailableHint"))}</p>
        </section>
      </main>
    );
  }

  const canInteract = nickname.trim().length > 0;
  const bothSucceeded = voteState === "success" && barrageState === "success";

  if (bothSucceeded) {
    return (
      <main className={styles.audiencePage}>
        <LanguageSwitcher />
        <section className={styles.audienceCard}>
          <span className={styles.eyebrow}>{t("appName")}</span>
          <h1>{t("audienceSubmitted")}</h1>
          <p className={styles.success} role="status">
            {t("audienceSubmittedHint")}
          </p>
        </section>
      </main>
    );
  }

  async function submitVote() {
    if (!canInteract || !selectedParticipant || voteState !== "idle") return;
    setVoteState("busy");
    setVoteError(null);
    try {
      const payload = votePayload ?? {
        participant_id: selectedParticipant,
        client_submission_id: newSubmissionId(),
      };
      if (!votePayload) setVotePayload(payload);
      await api.submitVote(accessToken, payload);
      setVoteState("success");
    } catch (cause) {
      setVoteState("idle");
      setVoteError(cause);
    }
  }

  async function submitBarrage() {
    if (!canInteract || !barrageText.trim() || barrageState !== "idle") return;
    setBarrageState("busy");
    setBarrageError(null);
    try {
      const payload = barragePayload ?? {
        nickname,
        raw_text: barrageText,
        client_submission_id: newSubmissionId(),
      };
      if (!barragePayload) setBarragePayload(payload);
      await api.submitBarrage(accessToken, payload);
      setBarrageState("success");
    } catch (cause) {
      setBarrageState("idle");
      setBarrageError(cause);
    }
  }

  return (
    <main className={styles.audiencePage}>
      <LanguageSwitcher />
      <section className={styles.audienceCard}>
        <span className={styles.eyebrow}>{t("audienceEyebrow")}</span>
        <h1>{form.topic}</h1>
        <p className={styles.audienceLede}>{t("audienceLede")}</p>

        <label className={styles.field}>
          <span>{t("audienceNickname")}</span>
          <input
            value={nickname}
            onChange={(event) => setNickname(event.target.value)}
            placeholder={t("audienceNicknamePlaceholder")}
            autoComplete="nickname"
            disabled={barragePayload !== null}
          />
        </label>

        {canInteract ? (
          <div className={styles.audienceSections}>
            <section className={styles.audienceSection}>
              <div className={styles.sectionHeading}>
                <span>{t("audienceVote")}</span>
                {voteState === "success" ? (
                  <strong>{t("audienceVoteSubmitted")}</strong>
                ) : null}
              </div>
              <p>{t("audienceVoteQuestion")}</p>
              <div className={styles.participantChoices}>
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
                className={styles.primaryButton}
                type="button"
                disabled={!canInteract || voteState !== "idle"}
                onClick={() => void submitVote()}
              >
                {voteState === "busy"
                  ? t("audienceSubmitting")
                  : t("audienceVoteSubmit")}
              </button>
              {voteError ? (
                <p className={styles.error}>{apiErrorMessage(voteError)}</p>
              ) : null}
            </section>

            <section className={styles.audienceSection}>
              <div className={styles.sectionHeading}>
                <span>{t("audienceBarrage")}</span>
                {barrageState === "success" ? (
                  <strong>{t("audienceBarrageSubmitted")}</strong>
                ) : null}
              </div>
              <p>{t("audienceBarrageHint")}</p>
              <textarea
                aria-label={t("audienceBarrage")}
                value={barrageText}
                onChange={(event) => setBarrageText(event.target.value)}
                placeholder={t("audienceBarragePlaceholder")}
                rows={5}
                disabled={
                  !canInteract ||
                  barrageState !== "idle" ||
                  barragePayload !== null
                }
              />
              <button
                className={styles.secondaryButton}
                type="button"
                disabled={
                  !canInteract || !barrageText.trim() || barrageState !== "idle"
                }
                onClick={() => void submitBarrage()}
              >
                {barrageState === "busy"
                  ? t("audienceSending")
                  : t("audienceBarrageSend")}
              </button>
              {barrageError ? (
                <p className={styles.error}>{apiErrorMessage(barrageError)}</p>
              ) : null}
            </section>
          </div>
        ) : null}

        {!canInteract ? (
          <p className={styles.helper}>{t("audienceEnterNickname")}</p>
        ) : null}
      </section>
    </main>
  );
}
