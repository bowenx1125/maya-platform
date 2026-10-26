"use client";

import { useEffect, useRef, useState } from "react";

import { DismissibleAlert } from "../dismissible-alert";
import { KindSticker, NoticeTraySlot } from "../ui/error-kit";
import { apiErrorMessage, PlatformApiError } from "../../lib/api";
import { cn } from "../../lib/utils";
import { useT } from "../../lib/i18n";
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

/*
 * Approved 02-audience family A, "cabinet controller": the phone is the pad
 * for the Student Live cabinet. Every decoration is aria-hidden, and the root
 * stops all animation under prefers-reduced-motion.
 * geometricPrecision: the self-hosted Lexend is hinted, so Chrome rounds each
 * glyph advance to whole pixels at small sizes (+23px on the 11px eyebrow);
 * this keeps fractional advances, as in the approved mock.
 */
const PAGE =
  "min-h-dvh bg-arc-bg bg-[linear-gradient(#00000010_1px,transparent_1px),linear-gradient(90deg,#00000010_1px,transparent_1px)] bg-size-[32px_32px] font-body leading-[normal] tracking-normal [text-rendering:geometricPrecision] text-ink motion-reduce:[&_*]:animate-none motion-reduce:[&_*]:transition-none";
const WRAP =
  "mx-auto max-w-[1180px] px-3.5 pt-[22px] pb-10 min-[900px]:px-10 min-[900px]:pt-10 min-[900px]:pb-[60px]";
const PAD =
  "relative rounded-[26px] border-3 border-ink bg-ink px-3.5 pt-[34px] pb-[18px] text-white shadow-[6px_6px_0_#FF4D8D] min-[900px]:rounded-[30px] min-[900px]:px-[26px] min-[900px]:pt-10 min-[900px]:pb-[26px]";
const SCREEN =
  "relative overflow-hidden rounded-xl border-3 border-[#333] bg-[#1d1d1d] px-4 py-3.5 after:pointer-events-none after:absolute after:inset-0 after:bg-[repeating-linear-gradient(#ffffff08_0_2px,transparent_2px_5px)] after:content-['']";
const PANEL =
  "relative rounded-2xl border-3 border-black bg-[#232323] p-3.5 shadow-[inset_0_3px_0_#333]";
const HEADING =
  "flex items-center gap-2.5 [&_h2]:m-0 [&_h2]:font-display [&_h2]:leading-[normal] [&_h2]:tracking-normal [&_h2]:text-xl [&_h2]:font-extrabold [&_h2]:text-white";
const OK_TAG =
  "ml-auto rotate-[-3deg] rounded-md border-2 border-black bg-ok px-2 py-[3px] text-xs leading-[normal] font-extrabold text-ink shadow-[2px_2px_0_#000]";
const STATUS_LINE = "m-0 mt-2.5 text-[13px] font-bold text-[#E8FFE0]";
const ARCADE =
  "relative cursor-pointer rounded-full border-3 border-black bg-main font-extrabold text-ink shadow-[0_6px_0_#9b1747,0_6px_0_3px_#000] active:translate-y-1.5 active:shadow-[0_0_0_3px_#000] disabled:cursor-default disabled:opacity-100 disabled:translate-y-[3px] disabled:bg-[#6b6b6b] disabled:text-[#cfcfcf] disabled:shadow-[0_3px_0_#333,0_3px_0_3px_#000]";
// Offsets measured against the mock: the button border (3px) shifts the containing block.
const STICKER_AT = "left-auto top-[-9px] right-[-11px] size-[26px]";
const VOTE_STICKER_AT = "left-auto top-[-4px] right-[-6px] size-[26px] z-[6]";
const SLOT_TONES = ["#FFE14D", "#67E8F9", "#A3E635"];
const LED_TONES = ["bg-main", "bg-[#FFE14D]", "bg-[#67E8F9]"];

function Leds({ mode }: { mode: "chase" | "off" | "ok" }) {
  return (
    <div
      aria-hidden="true"
      className="absolute top-[11px] right-0 left-0 flex justify-center gap-[9px]"
    >
      {Array.from({ length: 22 }, (_, index) => (
        <i
          key={index}
          className={cn(
            "size-[9px] rounded-full shadow-[0_0_0_2px_#000]",
            mode === "off"
              ? "bg-[#3a3a3a]"
              : mode === "ok"
                ? "bg-ok"
                : [
                    LED_TONES[
                      (index + 1) % 3 === 2 ? 1 : (index + 1) % 3 === 0 ? 2 : 0
                    ],
                    "animate-aud-blink",
                    index % 2 === 0 ? "[animation-delay:.6s]" : "",
                  ],
          )}
        />
      ))}
    </div>
  );
}

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
  const t = useT();
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
      <main className={PAGE}>
        <div className={WRAP}>
          <div className={PAD}>
            <Leds mode="chase" />
            <div className={SCREEN}>
              <p
                role="status"
                className="m-0 text-[15px] font-bold text-[#E8FFE0] after:ml-1.5 after:inline-block after:h-4 after:w-[9px] after:animate-aud-blink-cursor after:bg-[#E8FFE0] after:align-[-2px] after:content-['']"
              >
                {t("audienceLoading")}
              </p>
              <div aria-hidden="true" className="mt-3.5 grid gap-2.5">
                {["", "w-[70%]", "w-[45%]"].map((width) => (
                  <i
                    key={width}
                    className={cn(
                      "h-3.5 animate-aud-blink rounded-md border-2 border-black bg-[#2f2f2f]",
                      width,
                    )}
                  />
                ))}
              </div>
            </div>
          </div>
        </div>
      </main>
    );
  }
  if (loadError || !form) {
    return (
      <main className={PAGE}>
        <div className={WRAP}>
          <div className={PAD}>
            <Leds mode="off" />
            <div className={cn(SCREEN, "px-4 pt-[26px] pb-[22px] text-center")}>
              <div
                aria-hidden="true"
                className="relative mx-auto mt-1.5 h-[110px] w-[180px]"
              >
                <i className="absolute top-11 left-[30px] h-4 w-11 rounded-b-[40px] border-5 border-t-0 border-[#E8FFE0]" />
                <i className="absolute top-11 right-[30px] h-4 w-11 rounded-b-[40px] border-5 border-t-0 border-[#E8FFE0]" />
                <i className="absolute top-[76px] left-[78px] h-2.5 w-[22px] rounded-[50%] border-4 border-[#E8FFE0]" />
              </div>
              <svg
                aria-hidden="true"
                viewBox="0 0 60 50"
                fill="none"
                stroke="#FFE14D"
                strokeWidth="4"
                strokeLinejoin="round"
                strokeLinecap="round"
                className="absolute top-2 right-4 h-[50px] w-[60px] animate-aud-rise"
              >
                <path d="M30 6h14L30 22h14M8 26h12L8 40h12" />
              </svg>
              <section
                role="alert"
                className="mt-4 inline-block max-w-[320px] rotate-[-2deg] rounded-[10px] border-3 border-ink bg-[#FFE14D] px-4 py-3 text-ink shadow-[4px_4px_0_#111]"
              >
                <span className="text-[11px] font-extrabold tracking-[.04em]">
                  {t("appName")}
                </span>
                <h1 className="m-0 font-display text-[22px] tracking-normal font-extrabold leading-[normal] min-[900px]:text-[40px]">
                  {t("audienceUnavailable")}
                </h1>
                {/* Q2: the hint, never the server's wording. */}
                <p className="m-0 mt-1.5 text-sm leading-[normal] font-medium">
                  {t("audienceUnavailableHint")}
                </p>
              </section>
            </div>
            <svg
              aria-hidden="true"
              viewBox="0 0 120 60"
              fill="none"
              stroke="#111"
              strokeWidth="5"
              strokeLinecap="round"
              className="absolute -bottom-[34px] -left-1 h-[60px] w-[120px]"
            >
              <path d="M20 0c0 30 30 46 70 40" />
              <rect x="88" y="30" width="22" height="16" rx="3" fill="#111" />
              <path d="M110 34h8M110 42h8" />
            </svg>
          </div>
        </div>
      </main>
    );
  }

  /** Q1: a 5xx or unknown vote failure never shows the server's raw text. */
  function voteErrorMessage(cause: unknown): string {
    if (
      cause instanceof PlatformApiError &&
      cause.status >= 400 &&
      cause.status < 500
    )
      return apiErrorMessage(cause);
    return t("errorInternal");
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
    <main className={PAGE}>
      <div className={WRAP}>
        <section
          className={cn(PAD, submissionsClosed && "[&_form]:opacity-55")}
        >
          <Leds
            mode={
              submissionsClosed
                ? "off"
                : voteState === "success" || barrageState === "success"
                  ? "ok"
                  : "chase"
            }
          />
          <div className="min-[900px]:grid min-[900px]:grid-cols-[1.4fr_1fr] min-[900px]:items-end min-[900px]:gap-[18px]">
            <header className={SCREEN}>
              <span className="text-[11px] font-bold tracking-[.04em] text-[#FFE14D]">
                {t("audienceEyebrow")}
              </span>
              <h1 className="m-0 mt-1.5 font-display tracking-normal text-[26px] leading-[1.15] font-extrabold text-white min-[900px]:text-[40px]">
                {form.topic}
              </h1>
            </header>

            <label className="mt-3.5 flex flex-col gap-1.5 [&>span]:text-xs [&>span]:leading-[15px] [&>span]:font-bold [&>span]:tracking-[.04em] [&>span]:text-[#FFE14D]">
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
                className={cn(
                  "rounded-[10px] border-3 border-white bg-white px-3.5 py-3 text-base leading-[normal] disabled:opacity-100 font-semibold text-ink shadow-[inset_0_-4px_0_#ddd] focus:shadow-[0_0_0_3px_#111,5px_5px_0_3px_#FF4D8D] focus:outline-none",
                  !canInteract &&
                    "shadow-[0_0_0_3px_#111,5px_5px_0_3px_#FF4D8D]",
                )}
              />
            </label>
          </div>

          {canInteract ? (
            <div className="mt-4 grid gap-3.5 min-[900px]:grid-cols-[1.25fr_1fr] min-[900px]:gap-[18px]">
              <form
                className={PANEL}
                onSubmit={(event) => {
                  event.preventDefault();
                  void submitBarrage();
                }}
                aria-label={t("audienceBarrage")}
              >
                <div className={HEADING}>
                  <h2>{t("audienceBarrage")}</h2>
                  {barrageState === "success" ? (
                    <strong role="status" className={OK_TAG}>
                      {t("audienceBarrageSubmitted")}
                    </strong>
                  ) : null}
                </div>
                {form.round_no ? (
                  <span className="mt-2 inline-block rounded-full border-2 border-black bg-[#FFE14D] px-2.5 py-0.5 text-[11px] font-extrabold tracking-[.04em] text-ink">
                    {t("audienceRound")} {form.round_no}
                  </span>
                ) : null}
                {form.barrage_open === false ? (
                  <p
                    className="m-0 mt-2.5 ml-2 inline-block rotate-[-1.5deg] rounded-md border-2 border-black bg-[#FFE14D] px-2.5 py-1.5 text-[13px] font-extrabold text-ink"
                    role="status"
                  >
                    {t("audienceCollectionClosed")}
                  </p>
                ) : null}
                {syncFailed ? (
                  <p className={STATUS_LINE} role="status">
                    {t("audienceReconnecting")}
                  </p>
                ) : null}
                {barrageRetrying ? (
                  <p className={STATUS_LINE} role="status">
                    {t("audienceBusyRetrying")}
                  </p>
                ) : null}
                {barrageWaitSeconds > 0 ? (
                  <p className={STATUS_LINE} role="status">
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
                  className="mt-2.5 block min-h-[110px] w-full resize-none disabled:opacity-100 rounded-[10px] border-3 border-[#444] bg-[#0c0c0c] p-3 text-[15px] leading-normal font-medium text-[#E8FFE0] placeholder:text-[#8a8a8a] aria-invalid:border-err"
                  disabled={
                    !canInteract ||
                    submissionsClosed ||
                    form.barrage_open === false ||
                    barrageState === "busy"
                  }
                />
                <div className="mt-3 flex items-center justify-between">
                  {turnBound ? (
                    <span
                      id="message-count"
                      className="text-xs font-bold text-[#9CA3AF] tabular-nums"
                    >
                      {barrageText.length} / 300
                    </span>
                  ) : null}
                  <button
                    className={cn(ARCADE, "ml-auto size-[78px] text-[15px]")}
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
                    {barrageError ? (
                      <KindSticker kind="chat" on className={STICKER_AT} />
                    ) : null}
                    {barrageState === "busy"
                      ? t("audienceSending")
                      : t("audienceBarrageSend")}
                  </button>
                </div>
                {barrageError ? (
                  <DismissibleAlert
                    id="message-error"
                    resetKey={barrageError}
                    kind="chat"
                    transient
                  >
                    {apiErrorMessage(barrageError)}
                  </DismissibleAlert>
                ) : null}
              </form>
              <form
                className={PANEL}
                onSubmit={(event) => {
                  event.preventDefault();
                  void submitVote();
                }}
                aria-label={t("audienceVote")}
              >
                <div className={HEADING}>
                  <h2>{t("audienceVote")}</h2>
                  {voteState === "success" ? (
                    <strong role="status" className={OK_TAG}>
                      {t("audienceVoteSubmitted")}
                    </strong>
                  ) : null}
                </div>

                <div
                  className="mt-3 grid gap-2.5"
                  role="radiogroup"
                  aria-label={t("audienceVote")}
                >
                  {form.participants.map((participant, index) => (
                    <label
                      className="relative flex cursor-pointer items-center gap-3"
                      key={participant.participant_id}
                      style={{ ["--tone" as string]: SLOT_TONES[index % 3] }}
                    >
                      <input
                        type="radio"
                        name="participant"
                        className="peer absolute opacity-0"
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
                      <span
                        aria-hidden="true"
                        className="grid size-[46px] flex-none place-items-center rounded-full border-3 border-black bg-(--tone) shadow-[0_5px_0_#000] peer-checked:translate-y-[5px] peer-checked:shadow-[0_0_0_#000,0_0_0_4px_#FF4D8D] peer-focus-visible:outline-3 peer-focus-visible:outline-offset-4 peer-focus-visible:outline-main after:size-4 after:rounded-full after:bg-[#ffffff66] after:content-['']"
                      />
                      <span className="flex-1 rounded-l-md border-3 border-black bg-white py-[7px] pr-3.5 pl-3 text-[15px] font-bold text-ink [clip-path:polygon(0_0,100%_0,calc(100%-12px)_100%,0_100%)] peer-checked:bg-[#FFE4EF] peer-checked:shadow-[inset_0_0_0_2px_#FF4D8D] peer-disabled:opacity-60 [&_b]:mr-1.5 [&_b]:inline-block [&_b]:rounded [&_b]:border-2 [&_b]:border-black [&_b]:bg-(--tone) [&_b]:px-1.5">
                        <b>{participant.slot}</b> {participant.name}
                      </span>
                    </label>
                  ))}
                </div>
                <div className="relative mt-4 flex justify-center">
                  {voteError ? (
                    <KindSticker kind="bell" on className={VOTE_STICKER_AT} />
                  ) : null}
                  <button
                    className={cn(
                      ARCADE,
                      "size-24 text-[17px] min-[900px]:size-[110px]",
                    )}
                    type="submit"
                    disabled={
                      !canInteract || submissionsClosed || voteState !== "idle"
                    }
                  >
                    {voteState === "busy"
                      ? t("audienceSubmitting")
                      : t("audienceVoteSubmit")}
                  </button>
                </div>
                {voteRetrying ? (
                  <p className={STATUS_LINE} role="status">
                    {t("audienceBusyRetrying")}
                  </p>
                ) : null}
                {voteError ? (
                  <DismissibleAlert resetKey={voteError} kind="bell" transient>
                    {voteErrorMessage(voteError)}
                  </DismissibleAlert>
                ) : null}
              </form>
            </div>
          ) : (
            <div
              aria-hidden="true"
              className="mt-4 grid grid-cols-2 gap-3.5 opacity-35 min-[900px]:grid-cols-[1.25fr_1fr]"
            >
              <div className={cn(PANEL, "h-[150px]")} />
              <div
                className={cn(
                  PANEL,
                  "flex h-[150px] items-center justify-center gap-3",
                )}
              >
                {[0, 1, 2].map((key) => (
                  <i
                    key={key}
                    className="size-11 rounded-full border-3 border-black bg-[#555]"
                  />
                ))}
              </div>
            </div>
          )}
        </section>
        {/* Below 900px the shared notice tray sits here in the page flow,
            inside the page padding (14px sides, 40px bottom) like the mock. */}
        <NoticeTraySlot />
      </div>
    </main>
  );
}
