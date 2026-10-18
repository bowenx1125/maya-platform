/**
 * Shared @mention parsing for every @-capable chat input. Mirrors
 * backend/app/modules/workspace/mention_parse.py so client routing and the
 * server agree.
 *
 * Each "@" is matched against member names by the longest name the text
 * right after it starts with, so "@Scorer你是干嘛的" resolves to Scorer with
 * no space. An "@" that names no available member is ignored: the message is
 * treated as having no mention and the default reply rules apply.
 */

export type MentionMember = {
  id: string;
  name: string;
  available?: boolean;
};

export function mentionedMembers<T extends MentionMember>(
  text: string,
  members: readonly T[],
): T[] {
  const candidates = members
    .filter((member) => member.name && member.available !== false)
    .slice()
    .sort((a, b) => b.name.length - a.name.length);
  const visible = text.replace(/```[\s\S]*?```/g, " ");
  const found: T[] = [];
  for (let index = visible.indexOf("@"); index >= 0;) {
    const rest = visible.slice(index + 1);
    const match = candidates.find((member) => rest.startsWith(member.name));
    if (match && !found.some((member) => member.id === match.id)) {
      found.push(match);
    }
    index = visible.indexOf("@", index + 1);
  }
  return found;
}
