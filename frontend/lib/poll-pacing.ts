/**
 * Shared polling pace for chat / scoring / report refreshes.
 *
 * 60-student rerun (2026-10-19): students waiting on a busy server kept
 * polling every second or two, and those reads alone held the 2 vCPU host at
 * load 4.7-5.9, so the server's danger latch never cleared. Now, while the
 * server is shedding load, polls wait 5-10 s with backoff:
 *
 * - a 503 / 429 refusal (any request) or a busy code with
 *   `details.retry_after_seconds`, or a `Retry-After` header, and
 * - the `X-Maya-Poll-After` header the server adds to conversation reads
 *   while it is under pressure,
 *
 * each slow every poller for the next {@link PRESSURE_WINDOW_MS}. Calm
 * servers send neither, and polls keep their normal pace.
 */

export const POLL_AFTER_HEADER = "X-Maya-Poll-After";
/** Busy floor and ceiling for a poll's delay. */
export const BUSY_MIN_POLL_MS = 5_000;
export const BUSY_MAX_POLL_MS = 10_000;
/** A server-sent wait is honored up to this long. */
export const MAX_SERVER_WAIT_MS = 30_000;
/** How long one pressure signal keeps polls slow. */
export const PRESSURE_WINDOW_MS = 30_000;

let pressureUntil = 0;
let serverWaitMs = 0;
let now: () => number = () => Date.now();

/** Test hook: override the clock (null restores Date.now) and clear state. */
export function resetPollPacing(clock: (() => number) | null = null): void {
  now = clock ?? (() => Date.now());
  pressureUntil = 0;
  serverWaitMs = 0;
}

function parseSeconds(value: unknown): number | undefined {
  const seconds =
    typeof value === "number"
      ? value
      : typeof value === "string" && value.trim() !== ""
        ? Number(value)
        : NaN;
  return Number.isFinite(seconds) && seconds > 0 ? seconds : undefined;
}

/** Record that the server asked clients to wait `seconds` (undefined: busy). */
export function noteServerPressure(seconds?: number): void {
  const waitMs = Math.min(
    MAX_SERVER_WAIT_MS,
    Math.max(BUSY_MIN_POLL_MS, (seconds ?? 0) * 1000),
  );
  const at = now();
  // A fresh signal replaces the remembered wait once the old window ended.
  serverWaitMs = at < pressureUntil ? Math.max(serverWaitMs, waitMs) : waitMs;
  pressureUntil = Math.max(pressureUntil, at + PRESSURE_WINDOW_MS);
}

/** Read the pressure hints off any API response. */
export function notePollResponse(response: {
  status: number;
  headers: { get(name: string): string | null };
}): void {
  const hinted = parseSeconds(response.headers.get(POLL_AFTER_HEADER));
  if (hinted !== undefined) {
    noteServerPressure(hinted);
    return;
  }
  if (response.status === 503 || response.status === 429) {
    noteServerPressure(parseSeconds(response.headers.get("Retry-After")));
  }
}

/** Read the pressure hints off a thrown API error (status / details). */
export function notePollError(cause: unknown): void {
  if (!cause || typeof cause !== "object") return;
  const { status, details } = cause as {
    status?: unknown;
    details?: { retry_after_seconds?: unknown } | null;
  };
  if (status !== 503 && status !== 429) return;
  noteServerPressure(parseSeconds(details?.retry_after_seconds));
}

export function serverUnderPressure(): boolean {
  return now() < pressureUntil;
}

/**
 * Delay before the next poll. `baseMs` is the poller's own calm pace and
 * `attempt` counts polls since it started waiting (0 first). Under pressure
 * the delay is 5 s, doubling to 10 s, and never below what the server asked.
 */
export function nextPollDelay(baseMs: number, attempt = 0): number {
  if (!serverUnderPressure()) return baseMs;
  const backoff = Math.min(
    BUSY_MAX_POLL_MS,
    BUSY_MIN_POLL_MS * 2 ** Math.max(0, Math.min(attempt, 4)),
  );
  return Math.max(baseMs, backoff, serverWaitMs);
}
