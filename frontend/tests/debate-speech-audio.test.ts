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

describe("Debate speech output path", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("never wires the element into Web Audio (direct output at 0 dB)", () => {
    const ctor = vi.fn();
    vi.stubGlobal("AudioContext", ctor);
    const audio = document.createElement("audio");
    audio.volume = 0.2;
    const handle = bindDebateSpeechVolume(audio);
    handle.ensureRunning();
    handle.dispose();
    // rebind after dispose (ref callback re-run) still plays directly
    bindDebateSpeechVolume(audio).ensureRunning();
    expect(ctor).not.toHaveBeenCalled();
    expect(audio.volume).toBe(1);
  });
});
