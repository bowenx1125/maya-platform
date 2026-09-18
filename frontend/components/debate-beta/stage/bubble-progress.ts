/**
 * Progressive speech-bubble text for the Beta 3D stage.
 *
 * The bubble reveals a turn in step with the audio that speaks it, but the
 * stage only has room for the most recent few words. Cleaning mirrors
 * `bubbleLineFrom` in `beta-stage.tsx` so the two surfaces read the same
 * line; only the visible window differs.
 */

const BUBBLE_LIMIT = 116;

// Count and slice in Unicode code points, not UTF-16 units, so surrogate
// pairs (emoji etc.) are never split.
function codePoints(text: string): string[] {
  return Array.from(text);
}

function cleanSpeech(speech: string): string {
  return String(speech || "")
    .replace(/\s*\u3014[^\u3015]*\u3015\s*/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function bubbleProgressFrom(
  speech: string,
  elapsedSeconds: number,
  durationSeconds: number,
): string {
  const text = cleanSpeech(speech);
  if (!text) return "";

  const duration = Number(durationSeconds);
  const elapsed = Number(elapsedSeconds);
  if (!Number.isFinite(duration) || duration <= 0) return "";
  if (!Number.isFinite(elapsed) || elapsed <= 0) return "";

  if (elapsed >= duration) {
    const full = codePoints(text);
    return full.length <= BUBBLE_LIMIT
      ? text
      : full.slice(full.length - BUBBLE_LIMIT).join("");
  }

  const points = codePoints(text);
  const revealed = Math.max(
    1,
    Math.round((points.length * elapsed) / duration),
  );
  const window = points.slice(0, Math.min(revealed, points.length)).join("");
  const windowPoints = codePoints(window);
  return windowPoints.length <= BUBBLE_LIMIT
    ? window
    : windowPoints.slice(windowPoints.length - BUBBLE_LIMIT).join("");
}
