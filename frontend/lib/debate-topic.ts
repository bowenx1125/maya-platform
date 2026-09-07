/**
 * Validate the demo debate topic at the browser boundary.
 *
 * The server remains authoritative. This small mirror keeps an avoidable
 * invalid request from leaving the form and makes the language rule visible
 * while the teacher is editing. A topic may contain Latin-script letters,
 * Latin combining marks, numbers, punctuation, and ordinary Unicode space
 * separators. Combining marks are allowed only as part of a Latin grapheme.
 * Controls, bidi controls, and letters from another script are rejected.
 * Newlines and tabs are controls rather than topic whitespace.
 */

import { isLatinScriptLetter } from "./generated/latin-script-ranges";

const MARK = /^(?:\p{Nonspacing_Mark}|\p{Spacing_Mark})$/u;
const NUMBER = /^\p{Number}$/u;
const PUNCTUATION = /^\p{Punctuation}$/u;
const SPACE_SEPARATOR = /^\p{Zs}$/u;
const CONTROL = /^\p{Control}$/u;
const FORMAT = /^\p{Format}$/u;

export type DebateTopicValidationReason = "required" | "english";

export type DebateTopicValidation =
  | { valid: true; normalized: string }
  | { valid: false; reason: DebateTopicValidationReason };

function isLatinLetter(character: string): boolean {
  const codePoint = character.codePointAt(0);
  return codePoint !== undefined && isLatinScriptLetter(codePoint);
}

function isCombiningMark(character: string): boolean {
  return MARK.test(character);
}

function isAllowedNonLetter(
  character: string,
  canAcceptCombiningMark: boolean,
): boolean {
  return (
    (canAcceptCombiningMark && isCombiningMark(character)) ||
    NUMBER.test(character) ||
    PUNCTUATION.test(character) ||
    SPACE_SEPARATOR.test(character)
  );
}

/**
 * Return a trimmed topic only when it satisfies the frozen English-topic
 * boundary. The result never mutates the input string.
 */
export function validateDebateTopic(
  value: string,
  language: "en" | "zh" = "en",
): DebateTopicValidation {
  const normalized = value.trim();
  if (!normalized) return { valid: false, reason: "required" };

  let hasLatinLetter = false;
  let canAcceptCombiningMark = false;
  for (const character of value) {
    if (FORMAT.test(character) || CONTROL.test(character)) {
      return { valid: false, reason: "english" };
    }
    const point = character.codePointAt(0) ?? 0;
    const isHan =
      language === "zh" &&
      ((point >= 0x3400 && point <= 0x4dbf) ||
        (point >= 0x4e00 && point <= 0x9fff) ||
        (point >= 0xf900 && point <= 0xfaff) ||
        (point >= 0x20000 && point <= 0x2fa1f) ||
        (point >= 0x30000 && point <= 0x323af));
    if (isLatinLetter(character) || isHan) {
      hasLatinLetter = true;
      canAcceptCombiningMark = true;
      continue;
    }
    if (!isAllowedNonLetter(character, canAcceptCombiningMark)) {
      return { valid: false, reason: "english" };
    }
    if (!isCombiningMark(character)) canAcceptCombiningMark = false;
  }

  return hasLatinLetter
    ? { valid: true, normalized }
    : { valid: false, reason: "english" };
}
