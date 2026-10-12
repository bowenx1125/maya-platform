/**
 * The first-visit tour is owed once, to someone who has just registered.
 * Registration marks it for that account; finishing or skipping it clears the
 * mark. It lives in this browser only: if storage is unavailable or cleared,
 * the tour is simply not shown, which costs nothing.
 */

const PENDING = "maya.tour.pending";

export function markTourPending(userId: string): void {
  try {
    window.localStorage.setItem(PENDING, userId);
  } catch {
    // Private windows and blocked storage just skip the tour.
  }
}

export function tourPendingFor(userId: string): boolean {
  try {
    return window.localStorage.getItem(PENDING) === userId;
  } catch {
    return false;
  }
}

export function finishTour(): void {
  try {
    window.localStorage.removeItem(PENDING);
  } catch {
    // Nothing to clear.
  }
}
