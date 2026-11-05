import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEBATE_SPEECH_VOLUME,
  bindDebateSpeechVolume,
} from "../lib/debate-speech-audio";

function fakeCtx(state: "running" | "suspended") {
  const gain = { gain: { value: 0 }, connect: vi.fn() };
  const source = { connect: vi.fn() };
  const ctx = {
    state,
    destination: {},
    resume: vi.fn(async () => {
      ctx.state = "running";
    }),
    createGain: vi.fn(() => gain),
    createMediaElementSource: vi.fn(() => source),
  };
  return { ctx, gain, source };
}

describe("Debate speech volume", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("is +10 dB", () => {
    expect(DEBATE_SPEECH_VOLUME).toBeCloseTo(3.1622776601683795, 12);
  });

  it("keeps element volume at 1 and is idempotent without Web Audio", () => {
    vi.stubGlobal("AudioContext", undefined);
    vi.stubGlobal("webkitAudioContext", undefined);
    const audio = document.createElement("audio");
    const first = bindDebateSpeechVolume(audio);
    expect(bindDebateSpeechVolume(audio)).toBe(first);
    first.ensureRunning();
    expect(audio.volume).toBe(1);
    first.dispose();
  });

  it("wires gain only after the context is running; never while suspended", async () => {
    const { ctx, gain, source } = fakeCtx("suspended");
    vi.stubGlobal("AudioContext", function FakeCtx() {
      return ctx;
    });
    const audio = document.createElement("audio");
    audio.src = "blob:http://localhost/x";
    const handle = bindDebateSpeechVolume(audio);
    expect(ctx.createMediaElementSource).not.toHaveBeenCalled();
    handle.ensureRunning();
    expect(ctx.createMediaElementSource).not.toHaveBeenCalled();
    await Promise.resolve();
    await Promise.resolve();
    expect(ctx.resume).toHaveBeenCalled();
    expect(ctx.createMediaElementSource).toHaveBeenCalledTimes(1);
    expect(source.connect).toHaveBeenCalledWith(gain);
    expect(gain.connect).toHaveBeenCalledWith(ctx.destination);
    expect(gain.gain.value).toBeCloseTo(DEBATE_SPEECH_VOLUME);
    // dispose + rebind (ref callback re-run) reuses wiring, never re-creates
    handle.dispose();
    bindDebateSpeechVolume(audio).ensureRunning();
    await Promise.resolve();
    expect(ctx.createMediaElementSource).toHaveBeenCalledTimes(1);
  });
});
