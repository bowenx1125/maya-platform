/**
 * Debate turn speech playback volume.
 *
 * Every Immersive Debate speech clip plays at one absolute level:
 * +10 dB → linear 10^(10/20) ≈ 3.1623. HTMLMediaElement.volume caps at 1,
 * so the boost needs a Web Audio GainNode. Workspace / stage BGM is
 * untouched (see background-music.ts).
 *
 * Silence-safety rules (previous build went near-silent):
 * - One shared AudioContext for the page, never closed. Closing it left the
 *   element permanently wired to a dead graph (createMediaElementSource
 *   cannot be undone or re-created for the same element).
 * - The element is wired lazily, only once the context is *running*. Until
 *   then it plays directly at volume 1 (0 dB) — never muted.
 * - Every play (and ensureRunning) resumes the context, so a suspended
 *   context after a gesture/tab switch cannot strand wired audio.
 * - Cross-origin sources without CORS stay on the direct path (a
 *   MediaElementSource would output zeros for them).
 * - dispose() only detaches listeners; re-binding the same element (React
 *   ref callback re-runs) reuses the existing wiring.
 */
export const DEBATE_SPEECH_DB = 10;
export const DEBATE_SPEECH_VOLUME = 10 ** (DEBATE_SPEECH_DB / 20); // +10 dB ≈ 3.1623

type SpeechGainHandle = {
  /** Resume the shared context and wire the gain if possible. */
  ensureRunning: () => void;
  dispose: () => void;
};

type Wiring = { gain: GainNode };

let sharedCtx: AudioContext | null = null;
const wiringByAudio = new WeakMap<HTMLAudioElement, Wiring>();
const handleByAudio = new WeakMap<HTMLAudioElement, SpeechGainHandle>();

function audioContextCtor(): typeof AudioContext | undefined {
  if (typeof window === "undefined") return undefined;
  return (
    window.AudioContext ||
    (window as unknown as { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext
  );
}

function getCtx(): AudioContext | null {
  if (sharedCtx && sharedCtx.state !== "closed") return sharedCtx;
  const Ctor = audioContextCtor();
  if (!Ctor) return null;
  try {
    sharedCtx = new Ctor();
  } catch (error) {
    console.warn("[debate-speech] AudioContext unavailable; 0 dB direct", error);
    sharedCtx = null;
  }
  return sharedCtx;
}

/** Wire-able only when MediaElementSource will carry real samples. */
function sourceIsWireable(audio: HTMLAudioElement): boolean {
  const src = audio.currentSrc || audio.src;
  if (!src) return false;
  if (src.startsWith("blob:") || src.startsWith("data:")) return true;
  try {
    const url = new URL(src, window.location.href);
    if (url.origin === window.location.origin) return true;
  } catch {
    return false;
  }
  return audio.crossOrigin === "anonymous" || audio.crossOrigin === "use-credentials";
}

function tryWire(audio: HTMLAudioElement, ctx: AudioContext): void {
  const existing = wiringByAudio.get(audio);
  if (existing) {
    existing.gain.gain.value = DEBATE_SPEECH_VOLUME;
    return;
  }
  // Only wire a running context: a suspended one would silence the element.
  if (ctx.state !== "running" || !sourceIsWireable(audio)) return;
  try {
    const source = ctx.createMediaElementSource(audio);
    const gain = ctx.createGain();
    gain.gain.value = DEBATE_SPEECH_VOLUME;
    source.connect(gain);
    gain.connect(ctx.destination);
    wiringByAudio.set(audio, { gain });
  } catch (error) {
    // Element stays on the direct path (0 dB) — audible, just not boosted.
    console.warn("[debate-speech] gain graph failed; 0 dB direct", error);
  }
}

export function bindDebateSpeechVolume(
  audio: HTMLAudioElement,
): SpeechGainHandle {
  audio.volume = 1;
  const existing = handleByAudio.get(audio);
  if (existing) return existing;

  const ensureRunning = () => {
    audio.volume = 1;
    const ctx = getCtx();
    if (!ctx) return;
    if (ctx.state === "running") {
      tryWire(audio, ctx);
      return;
    }
    void ctx
      .resume()
      .then(() => tryWire(audio, ctx))
      .catch((error: unknown) => {
        console.warn("[debate-speech] AudioContext resume failed", error);
      });
  };
  const onPlay = () => ensureRunning();
  audio.addEventListener("play", onPlay);

  const handle: SpeechGainHandle = {
    ensureRunning,
    dispose: () => {
      audio.removeEventListener("play", onPlay);
      handleByAudio.delete(audio);
    },
  };
  handleByAudio.set(audio, handle);
  return handle;
}
