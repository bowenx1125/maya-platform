/** Topic script is independent of the requested output language. */
export type DebateTopicValidation =
  { valid: true; normalized: string } | { valid: false; reason: "required" };

export function validateDebateTopic(value: string): DebateTopicValidation {
  return value.trim()
    ? { valid: true, normalized: value.trim() }
    : { valid: false, reason: "required" };
}
