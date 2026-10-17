import { AVATAR_STATES, type AvatarState } from "../avatar";

const KNOWN = new Set<string>(AVATAR_STATES);

/**
 * Adapt any motion token onto the frozen five-state vocabulary.
 * Unknown / missing → idle (architecture gate: no parallel state machine).
 */
export function normalizeAvatarState(value: unknown): AvatarState {
  if (typeof value === "string" && KNOWN.has(value)) {
    return value as AvatarState;
  }
  return "idle";
}
