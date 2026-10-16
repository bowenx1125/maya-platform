/**
 * Sign-in queue persistence.
 *
 * Only the server-issued queue ticket and the typed username survive a page
 * refresh, in sessionStorage (this tab only). The password is never written to
 * any storage: after a reload the student re-types it and resubmits with the
 * same ticket, so the place in line is kept while the ticket is still alive.
 */

export const LOGIN_QUEUE_STORAGE_KEY = "maya.loginQueue.v1";

export type LoginQueueNotice = {
  position: number;
  retryAfterSeconds: number;
  queueLength: number;
  estimatedWaitSeconds: number;
  ticketExpiresInSeconds?: number;
  ticket?: string;
  /** True while the network is down and the client keeps retrying. */
  reconnecting?: boolean;
};

export type SavedLoginQueue = {
  ticket: string;
  username: string;
  /** Position when the ticket was first issued; the progress bar baseline. */
  initialPosition: number;
  position: number;
  /** Epoch milliseconds after which the server has dropped the ticket. */
  expiresAt: number;
};

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function loadLoginQueue(now = Date.now()): SavedLoginQueue | null {
  const store = storage();
  const raw = store?.getItem(LOGIN_QUEUE_STORAGE_KEY);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<SavedLoginQueue>;
    if (
      typeof value.ticket === "string" &&
      UUID_PATTERN.test(value.ticket) &&
      typeof value.username === "string" &&
      typeof value.expiresAt === "number" &&
      value.expiresAt > now
    ) {
      const position = Number.isSafeInteger(value.position)
        ? Math.max(0, value.position as number)
        : 0;
      const initialPosition = Number.isSafeInteger(value.initialPosition)
        ? Math.max(position, value.initialPosition as number)
        : position;
      return {
        ticket: value.ticket,
        username: value.username,
        position,
        initialPosition,
        expiresAt: value.expiresAt,
      };
    }
  } catch {
    // A corrupt entry is dropped below.
  }
  store?.removeItem(LOGIN_QUEUE_STORAGE_KEY);
  return null;
}

export function saveLoginQueue(
  username: string,
  notice: LoginQueueNotice,
  previous: SavedLoginQueue | null,
  now = Date.now(),
): SavedLoginQueue | null {
  if (!notice.ticket) return previous;
  const sameTicket = previous?.ticket === notice.ticket;
  const next: SavedLoginQueue = {
    ticket: notice.ticket,
    username,
    position: notice.position,
    initialPosition: sameTicket
      ? Math.max(previous.initialPosition, notice.position)
      : notice.position,
    expiresAt: now + (notice.ticketExpiresInSeconds ?? 60) * 1000,
  };
  try {
    storage()?.setItem(LOGIN_QUEUE_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Storage full or disabled: the in-memory ticket still keeps the place.
  }
  return next;
}

export function clearLoginQueue(): void {
  try {
    storage()?.removeItem(LOGIN_QUEUE_STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}

/** Fraction of the line already passed, kept inside (0, 1) while waiting. */
export function loginQueueProgress(
  position: number,
  initialPosition: number,
): number {
  const start = Math.max(initialPosition, position, 0) + 1;
  const done = (start - (Math.max(position, 0) + 1)) / start;
  return Math.min(0.95, Math.max(0.05, done + (1 - done) / (start + 1)));
}
