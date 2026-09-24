import { describe, expect, it } from "vitest";

import {
  TTS_COMPLETE_TOLERANCE_SECONDS,
  ttsPlaybackPhase,
} from "../lib/chat-tts-playback";

describe("chat TTS playback state", () => {
  it("rejects a half-complete clock", () => {
    const duration = 8;
    expect(
      ttsPlaybackPhase({
        ended: true,
        currentTime: duration / 2,
        duration,
      }),
    ).toBe("incomplete");
    expect(
      ttsPlaybackPhase({
        ended: false,
        currentTime: duration - TTS_COMPLETE_TOLERANCE_SECONDS,
        duration,
      }),
    ).toBe("incomplete");
    expect(
      ttsPlaybackPhase({
        ended: true,
        currentTime: duration - TTS_COMPLETE_TOLERANCE_SECONDS - 0.001,
        duration,
      }),
    ).toBe("incomplete");
    expect(
      ttsPlaybackPhase({
        ended: true,
        currentTime: Number.NaN,
        duration,
      }),
    ).toBe("incomplete");
    expect(
      ttsPlaybackPhase({
        ended: true,
        currentTime: duration,
        duration: Number.NaN,
      }),
    ).toBe("incomplete");
  });

  it("is complete only when playback ended and currentTime is within 0.05s of duration", () => {
    const duration = 8;
    expect(
      ttsPlaybackPhase({
        ended: true,
        currentTime: duration - TTS_COMPLETE_TOLERANCE_SECONDS,
        duration,
      }),
    ).toBe("complete");
    expect(
      ttsPlaybackPhase({
        ended: true,
        currentTime: duration,
        duration,
      }),
    ).toBe("complete");
    expect(
      ttsPlaybackPhase({
        ended: true,
        currentTime: duration + 0.01,
        duration,
      }),
    ).toBe("complete");
  });
});
