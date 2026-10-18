/**
 * Shared @mention draft insertion for every chat surface that offers
 * mention autocomplete. Always leaves exactly one space after the name
 * so typing continues as `@Name …`.
 */

export type MentionInsertResult = {
  next: string;
  /** Index after the single trailing space following the inserted name. */
  caret: number;
};

export function applyMentionInsert(
  draft: string,
  label: string,
): MentionInsertResult {
  const at = draft.lastIndexOf("@");
  if (at < 0) {
    const next = `${draft}@${label} `;
    return { next, caret: next.length };
  }
  const afterToken = draft.slice(at + 1).replace(/^[^\s@]*/, "");
  const spaceAlready = afterToken.startsWith(" ");
  const inserted = `@${label}${spaceAlready ? "" : " "}`;
  const next = `${draft.slice(0, at)}${inserted}${afterToken}`;
  // Always sit after the one space that follows the name.
  const caret = at + label.length + 2;
  return { next, caret };
}

export function placeMentionCaret(
  el: HTMLTextAreaElement | HTMLInputElement | null | undefined,
  caret: number,
): void {
  if (!el) return;
  el.focus();
  el.setSelectionRange(caret, caret);
}

/** Where the picker last inserted `@Name ` (its auto space included). */
export type InsertedMention = { at: number; label: string };

export function insertedMentionAt(
  draft: string,
  label: string,
): InsertedMention {
  const { caret } = applyMentionInsert(draft, label);
  return { at: caret - label.length - 2, label };
}

/**
 * Backspace with the caret right after a picker-inserted `@Name `: remove
 * the space and the name together, keeping the "@" so the picker can reopen.
 * Returns null for anything else, so ordinary text deletes char by char.
 */
export function collapseMentionOnBackspace(
  draft: string,
  caret: number,
  inserted: InsertedMention | null,
): MentionInsertResult | null {
  if (!inserted) return null;
  const token = `@${inserted.label} `;
  const end = inserted.at + token.length;
  if (caret !== end || draft.slice(inserted.at, end) !== token) return null;
  const next = `${draft.slice(0, inserted.at + 1)}${draft.slice(end)}`;
  return { next, caret: inserted.at + 1 };
}
