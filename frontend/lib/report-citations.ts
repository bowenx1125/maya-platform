// The server numbers report citations ([1], [2] and a source list). This is
// the last guard: a raw `[evidence:…]` token from an older revision or an
// unresolved source must never reach a teacher's screen or download.
const RAW_CITATION = /[ \t]*\[evidence:[^\]\n]*\]/g;

export function cleanReportCitations(markdown: string): string {
  if (!markdown.includes("[evidence:")) return markdown;
  return markdown
    .replace(RAW_CITATION, "")
    .replace(/[ \t]+(?=[。，；、])/g, "")
    .replace(/(?<=\S)[ \t]{2,}(?=\S)/g, " ");
}

// Chinese reports are counted in characters, so the unit is 字, not 词.
export function reportLengthUnit(locale: string): string {
  return locale === "zh" ? "字" : "words";
}
