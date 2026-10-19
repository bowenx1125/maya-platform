import { PlatformApiError } from "../../lib/api";

/**
 * How the anonymous audience form waits when the server is busy.
 *
 * Load plan 2026-10-19: 60 viewers polled every 2 s and resent nothing on a
 * 503, so a busy server got the same load until it failed. The form now
 * backs off (2 s up to 10 s) on 503/429/network errors, honours
 * Retry-After, and retries a vote or barrage refused with 503 under the same
 * client_submission_id, so a retry is never counted twice.
 */

export const FORM_POLL_MIN_MS = 2000;
export const FORM_POLL_MAX_MS = 10000;
export const SUBMIT_RETRY_ATTEMPTS = 5;
const SUBMIT_RETRY_BASE_MS = 1000;
const AUDIENCE_ID_KEY = "maya-audience-id";

/** Server-requested wait (Retry-After / retry_after_seconds), in ms. */
export function retryAfterMs(cause: unknown): number {
  if (!(cause instanceof PlatformApiError)) return 0;
  const seconds = cause.details?.retry_after_seconds;
  return typeof seconds === "number" && Number.isFinite(seconds) && seconds > 0
    ? seconds * 1000
    : 0;
}

/** Next form poll: 2 s after a success, doubling to 10 s after failures. */
export function nextFormPollDelay(previousMs: number, cause: unknown): number {
  if (cause === null || cause === undefined) return FORM_POLL_MIN_MS;
  const backedOff = Math.min(
    FORM_POLL_MAX_MS,
    Math.max(FORM_POLL_MIN_MS, previousMs * 2),
  );
  return Math.max(backedOff, retryAfterMs(cause));
}

/** 503: the server shed this request; it is safe to send again. */
export function isBusyRefusal(cause: unknown): boolean {
  return cause instanceof PlatformApiError && cause.status === 503;
}

/** 429: this audience member is sending too fast. */
export function isRateLimited(cause: unknown): boolean {
  return cause instanceof PlatformApiError && cause.status === 429;
}

/** Wait before resend ``attempt`` (0-based): 1, 2, 4 … s, at most 10 s. */
export function submitRetryDelay(attempt: number, cause: unknown): number {
  const backedOff = Math.min(
    FORM_POLL_MAX_MS,
    SUBMIT_RETRY_BASE_MS * 2 ** attempt,
  );
  return Math.max(backedOff, retryAfterMs(cause));
}

let memoryAudienceId: string | null = null;

function randomId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}

/**
 * A stable id for this browser, sent as ``X-Maya-Audience``.
 *
 * Classroom devices share one NAT address, so the server counts one vote and
 * paces barrages per browser, not per IP. Storage can be unavailable (private
 * mode, blocked site data); then the id lives for this page only.
 */
export function audienceId(): string {
  if (memoryAudienceId) return memoryAudienceId;
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(AUDIENCE_ID_KEY);
  } catch {
    stored = null;
  }
  const id = stored && stored.length >= 8 ? stored : randomId();
  if (!stored) {
    try {
      window.localStorage.setItem(AUDIENCE_ID_KEY, id);
    } catch {
      // Page-lifetime id only.
    }
  }
  memoryAudienceId = id;
  return id;
}

/** Tests only: forget the cached id. */
export function resetAudienceIdForTests(): void {
  memoryAudienceId = null;
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
