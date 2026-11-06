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

function firstCodePoint(text: string): string {
  return codePoints(text)[0] ?? "";
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
  // Reject unset / failed durations. POSITIVE_INFINITY means playback has
  // started but media metadata has not arrived yet — still mount the bubble.
  if (Number.isNaN(duration) || duration <= 0) return "";
  if (!Number.isFinite(elapsed) || elapsed < 0) return "";

  if (!Number.isFinite(duration)) {
    return firstCodePoint(text);
  }

  // At play start, expose one code point so the 3D bubble mounts with voice.
  if (elapsed === 0) {
    return firstCodePoint(text);
  }

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

/** Two animation frames so React can commit the bubble before audio starts. */
export function waitForBubblePaint(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof requestAnimationFrame !== "function") {
      resolve();
      return;
    }
    requestAnimationFrame(() => {
      requestAnimationFrame(() => resolve());
    });
  });
}
