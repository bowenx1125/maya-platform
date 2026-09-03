import type { DebateDetail } from "./api/platform";

/**
 * The one place a Debate's round count is read on the client.
 *
 * `round_count` is not a field of `DebateDetail`: the count lives in the frozen
 * rule snapshot the server keeps. Reading it as a property silently yields
 * nothing and falls back to two, which is why a three-Agent four-round debate
 * looked incomplete — its twelve turns were compared against six, and the
 * teacher's classroom-interaction button disappeared.
 */
const MIN_ROUND_COUNT = 2;
const MAX_ROUND_COUNT = 5;
const DEFAULT_ROUND_COUNT = 2;

function valid(value: unknown): number | null {
  return typeof value === "number" &&
    Number.isInteger(value) &&
    value >= MIN_ROUND_COUNT &&
    value <= MAX_ROUND_COUNT
    ? value
    : null;
}

export function debateRoundCount(detail: DebateDetail): number {
  const carrier = detail as DebateDetail & {
    round_count?: unknown;
    rule_snapshot_json?: unknown;
  };
  const direct = valid(carrier.round_count);
  if (direct !== null) return direct;
  if (typeof carrier.rule_snapshot_json === "string") {
    try {
      const snapshot: unknown = JSON.parse(carrier.rule_snapshot_json);
      if (snapshot && typeof snapshot === "object") {
        const fromSnapshot = valid(
          (snapshot as { round_count?: unknown }).round_count,
        );
        if (fromSnapshot !== null) return fromSnapshot;
      }
    } catch {
      // A malformed snapshot falls back rather than sizing from garbage.
    }
  }
  return DEFAULT_ROUND_COUNT;
}

/** Every participant speaks once per round. */
export function expectedTurnCount(detail: DebateDetail): number {
  return detail.participants.length * debateRoundCount(detail);
}
