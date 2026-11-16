import { describe, expect, it } from "vitest";
import { stageMouthVisual } from "../components/debate-beta/stage/mouth-sync";

/** Pre-fix gate: mouth waited for status==="playing" plus live audio. */
function legacyStageMouthVisual(args: {
  derived: "idle" | "listening" | "thinking" | "speaking";
  playbackStatus: "ready" | "playing" | "paused" | "waiting_next";
  audioPlayingTurnId: string | null;
  currentTurnId: string | null;
  mediaRetryNeeded: boolean;
}): "idle" | "listening" | "thinking" | "speaking" {
  if (
    args.derived === "speaking" &&
    (args.playbackStatus !== "playing" ||
      args.mediaRetryNeeded ||
      args.audioPlayingTurnId !== args.currentTurnId)
  ) {
    return "idle";
  }
  return args.derived;
}

describe("stageMouthVisual", () => {
  const speaker = "agent-a";
  const turn = "turn-1";

  it("closes the ready→playing ack gap: audio start to first mouth frame", () => {
    // At audio start (startEarly): status still "ready", derived is thinking,
    // onPlaying / play() has set audioPlayingTurnId. Legacy kept mouth idle
    // until started_ack flipped status to playing (often 100–400ms+ later).
    const atAudioStart = {
      derived: "thinking" as const,
      participantId: speaker,
      speakerId: speaker,
      audioPlayingTurnId: turn,
      currentTurnId: turn,
      mediaRetryNeeded: false,
    };
    expect(
      legacyStageMouthVisual({
        derived: "thinking",
        playbackStatus: "ready",
        audioPlayingTurnId: turn,
        currentTurnId: turn,
        mediaRetryNeeded: false,
      }),
    ).toBe("thinking");
    // Even after derived becomes speaking from a premature event, legacy still
    // idled until status===playing.
    expect(
      legacyStageMouthVisual({
        derived: "speaking",
        playbackStatus: "ready",
        audioPlayingTurnId: turn,
        currentTurnId: turn,
        mediaRetryNeeded: false,
      }),
    ).toBe("idle");
    expect(stageMouthVisual(atAudioStart)).toBe("speaking");
  });

  it("starts speaking from live audio even while playback status is still ready", () => {
    expect(
      stageMouthVisual({
        derived: "thinking",
        participantId: speaker,
        speakerId: speaker,
        audioPlayingTurnId: turn,
        currentTurnId: turn,
        mediaRetryNeeded: false,
      }),
    ).toBe("speaking");
  });

  it("keeps listeners idle while the live speaker's mouth runs", () => {
    expect(
      stageMouthVisual({
        derived: "listening",
        participantId: "agent-b",
        speakerId: speaker,
        audioPlayingTurnId: turn,
        currentTurnId: turn,
        mediaRetryNeeded: false,
      }),
    ).toBe("listening");
  });

  it("stops the mouth when audio ends before waiting_next arrives", () => {
    expect(
      stageMouthVisual({
        derived: "speaking",
        participantId: speaker,
        speakerId: speaker,
        audioPlayingTurnId: null,
        currentTurnId: turn,
        mediaRetryNeeded: false,
      }),
    ).toBe("idle");
  });

  it("does not speak during media retry or mismatched turn ids", () => {
    expect(
      stageMouthVisual({
        derived: "speaking",
        participantId: speaker,
        speakerId: speaker,
        audioPlayingTurnId: turn,
        currentTurnId: turn,
        mediaRetryNeeded: true,
      }),
    ).toBe("idle");
    expect(
      stageMouthVisual({
        derived: "thinking",
        participantId: speaker,
        speakerId: speaker,
        audioPlayingTurnId: "other-turn",
        currentTurnId: turn,
        mediaRetryNeeded: false,
      }),
    ).toBe("thinking");
  });
});
