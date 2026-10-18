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
