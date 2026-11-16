/** Extract a TTS Tone line from AGENT.md (mirrors backend tone.extract_tone). */

const TONE_LINE = /^\s*[-*]\s*Tone\s*:\s*(.+?)\s*$/im;

export function extractTone(
  agentMd: string | null | undefined,
  fallback?: string | null,
  maxChars = 500,
): string | null {
  if (typeof agentMd === "string") {
    const match = TONE_LINE.exec(agentMd);
    if (match?.[1]) {
      const text = match[1].replace(/\s+/g, " ").trim();
      if (text) return text.slice(0, maxChars);
    }
  }
  if (typeof fallback === "string") {
    const text = fallback.trim();
    if (text) return text.slice(0, maxChars);
  }
  return null;
}

/**
 * Best-effort Check-card fields from live AGENT.md for create/edit.
 * Identity and Position stay visible when present; Tone uses extractTone.
 */
export function cardFromAgentMd(
  agentMd: string,
  fallbackTone?: string | null,
): {
  identity: string;
  position: string;
  reasoning: string[];
  speaking_style: string;
  voice_style: string | null;
  dropped: [];
} {
  const identity =
    /^#\s+(.+)$/m.exec(agentMd)?.[1]?.trim() ||
    sectionBody(agentMd, "Identity")
      .split("\n")[0]
      ?.replace(/^[-*]\s*/, "") ||
    "";
  const position = sectionBody(agentMd, "Initial position").trim();
  const speaking = sectionBody(agentMd, "Speaking style").trim();
  const tone = extractTone(agentMd, fallbackTone, 120);
  const reasoning = sectionList(agentMd, "Core values").slice(0, 5);
  return {
    identity: identity || "—",
    position,
    reasoning,
    speaking_style: speaking,
    voice_style: tone,
    dropped: [],
  };
}

function sectionBody(md: string, heading: string): string {
  const re = new RegExp(
    `^##\\s+${escapeReg(heading)}\\s*\\n([\\s\\S]*?)(?=^##\\s+|$)`,
    "im",
  );
  return re.exec(md)?.[1]?.trim() ?? "";
}

function sectionList(md: string, heading: string): string[] {
  return sectionBody(md, heading)
    .split("\n")
    .map((line) => line.replace(/^[-*]\s+/, "").trim())
    .filter(Boolean);
}

function escapeReg(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
