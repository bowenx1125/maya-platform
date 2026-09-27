/** Playback is complete only after the element has ended near its duration. */

export const TTS_COMPLETE_TOLERANCE_SECONDS = 0.05;

export type TtsPlaybackClock = {
  ended: boolean;
  currentTime: number;
  duration: number;
};

export type TtsPlaybackPhase = "complete" | "incomplete";

export function ttsPlaybackPhase(clock: TtsPlaybackClock): TtsPlaybackPhase {
  if (clock.ended !== true) return "incomplete";
  if (!Number.isFinite(clock.duration) || clock.duration <= 0)
    return "incomplete";
  if (!Number.isFinite(clock.currentTime) || clock.currentTime < 0)
    return "incomplete";
  if (clock.currentTime >= clock.duration - TTS_COMPLETE_TOLERANCE_SECONDS) {
    return "complete";
  }
  return "incomplete";
}
