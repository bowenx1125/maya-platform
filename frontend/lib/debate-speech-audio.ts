/**
 * Debate turn speech playback volume.
 *
 * Every Immersive Debate speech clip plays at this one level. 1.5× the
 * browser default (HTMLMediaElement.volume = 1), so clips that used to
 * sit at full element volume land 50% louder via a GainNode. Element
 * volume stays at 1; the boost is the gain. Workspace / stage BGM is
 * untouched (see background-music.ts).
 */
export const DEBATE_SPEECH_VOLUME = 1.5;

type SpeechGainHandle = {
  /** Keep the AudioContext awake across user-gesture-gated play(). */
  ensureRunning: () => void;
  dispose: () => void;
};

/**
 * Route `audio` through a shared GainNode at DEBATE_SPEECH_VOLUME.
 * Safe to call once per element; a second call is a no-op that returns
 * the same dispose. Falls back to element.volume = 1 when Web Audio is
 * unavailable (jsdom / legacy).
 */
export function bindDebateSpeechVolume(
  audio: HTMLAudioElement,
): SpeechGainHandle {
  const existing = speechGainByAudio.get(audio);
  if (existing) return existing;

  audio.volume = 1;

  const AudioCtx =
    typeof window !== "undefined"
      ? window.AudioContext ||
        (
          window as unknown as {
            webkitAudioContext?: typeof AudioContext;
          }
        ).webkitAudioContext
      : undefined;

  if (!AudioCtx) {
    const handle: SpeechGainHandle = {
      ensureRunning: () => undefined,
      dispose: () => {
        speechGainByAudio.delete(audio);
      },
    };
    speechGainByAudio.set(audio, handle);
    return handle;
  }

  let ctx: AudioContext | null = null;
  let disposed = false;

  const ensureGraph = (): AudioContext | null => {
    if (disposed) return null;
    if (ctx) return ctx;
    try {
      ctx = new AudioCtx();
      const source = ctx.createMediaElementSource(audio);
      const gain = ctx.createGain();
      gain.gain.value = DEBATE_SPEECH_VOLUME;
      source.connect(gain);
      gain.connect(ctx.destination);
      return ctx;
    } catch {
      // createMediaElementSource throws if the element is already wired.
      ctx = null;
      return null;
    }
  };

  const handle: SpeechGainHandle = {
    ensureRunning: () => {
      const running = ensureGraph();
      if (running && running.state === "suspended") {
        void running.resume();
      }
    },
    dispose: () => {
      disposed = true;
      speechGainByAudio.delete(audio);
      if (ctx) {
        void ctx.close();
        ctx = null;
      }
    },
  };
  speechGainByAudio.set(audio, handle);
  // Build the graph eagerly so the first play() is not racing graph setup.
  ensureGraph();
  return handle;
}

const speechGainByAudio = new WeakMap<HTMLAudioElement, SpeechGainHandle>();
