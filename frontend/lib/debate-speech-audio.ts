/**
 * Debate turn speech playback volume.
 *
 * Every Immersive Debate speech clip plays at one absolute level:
 * 0 dB → linear 1.0. At 0 dB no Web Audio gain is needed, so the element
 * plays straight to the output with `audio.volume = 1`.
 *
 * Do NOT route speech through createMediaElementSource: once wired, the
 * element only sounds through that AudioContext. The stage ref callback
 * re-binds on renders and dispose() closed the context, which silenced
 * speech (captions stalled after a few characters because they follow
 * audio progress). Cross-origin clips without CORS also output silence.
 */
export const DEBATE_SPEECH_VOLUME = 1.0; // 0 dB

type SpeechGainHandle = {
  /** Kept for call-site compatibility; no Web Audio graph exists. */
  ensureRunning: () => void;
  dispose: () => void;
};

export function bindDebateSpeechVolume(
  audio: HTMLAudioElement,
): SpeechGainHandle {
  audio.volume = DEBATE_SPEECH_VOLUME;
  const existing = speechHandleByAudio.get(audio);
  if (existing) return existing;
  const handle: SpeechGainHandle = {
    ensureRunning: () => {
      if (audio.volume !== DEBATE_SPEECH_VOLUME) audio.volume = DEBATE_SPEECH_VOLUME;
    },
    dispose: () => {
      speechHandleByAudio.delete(audio);
    },
  };
  speechHandleByAudio.set(audio, handle);
  return handle;
}

const speechHandleByAudio = new WeakMap<HTMLAudioElement, SpeechGainHandle>();
