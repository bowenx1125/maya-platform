import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEBATE_SPEECH_VOLUME,
  bindDebateSpeechVolume,
} from "../lib/debate-speech-audio";

describe("Debate speech volume", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("exports the unified 0 dB (1.0) level", () => {
    expect(DEBATE_SPEECH_VOLUME).toBe(1.0);
  });

  it("keeps element volume at 1 and is idempotent without Web Audio", () => {
    vi.stubGlobal("AudioContext", undefined);
    vi.stubGlobal("webkitAudioContext", undefined);
    const audio = document.createElement("audio");
    const first = bindDebateSpeechVolume(audio);
    const second = bindDebateSpeechVolume(audio);
    expect(first).toBe(second);
    expect(audio.volume).toBe(1);
    first.ensureRunning();
    first.dispose();
  });
});
