import { describe, expect, it } from "vitest";

import {
  createPerformancePlayer,
  parsePerformanceTimeline,
  type PerformanceTimeline,
} from "../components/stage3d/performance-player";

const TIMELINE: PerformanceTimeline = {
  version: 2,
  duration: 4,
  emotion: "calm",
  posture: "open_palm_listening",
  viseme: "timed",
  events: [
    { t: 1, type: "gesture", clip: "emphasis", dur: 1.2, fade_ms: 150 },
    { t: 3, type: "gesture", clip: "headshake", dur: 0.8, fade_ms: 100 },
  ],
  visemes: [
    { t0: 0, t1: 0.4, viseme: "viseme_a", jaw: 0.9 },
    { t0: 0.5, t1: 0.9, viseme: "viseme_i", jaw: 0.5 },
    { t0: 2, t1: 2.3, viseme: "viseme_u", jaw: 0.7 },
  ],
};

describe("parsePerformanceTimeline", () => {
  it("accepts a compiled timeline", () => {
    const parsed = parsePerformanceTimeline(
      JSON.parse(JSON.stringify(TIMELINE)),
    );
    expect(parsed).not.toBeNull();
    expect(parsed?.duration).toBe(4);
    expect(parsed?.events).toHaveLength(2);
    expect(parsed?.visemes).toHaveLength(3);
  });

  it("rejects wrong versions and non-objects", () => {
    expect(parsePerformanceTimeline(null)).toBeNull();
    expect(parsePerformanceTimeline({ ...TIMELINE, version: 1 })).toBeNull();
    expect(parsePerformanceTimeline({ version: 2, duration: 0 })).toBeNull();
  });

  it("drops malformed events and windows instead of failing", () => {
    const parsed = parsePerformanceTimeline({
      ...TIMELINE,
      events: [
        { t: "x", type: "gesture", clip: "emphasis", dur: 1, fade_ms: 100 },
        { t: 0.5, type: "gesture", clip: "not_a_clip", dur: 1, fade_ms: 100 },
        { t: 0.5, type: "gesture", clip: "nod", dur: 1, fade_ms: 100 },
      ],
      visemes: [
        { t0: 0.2, t1: 0.1, viseme: "a", jaw: 1 },
        { t0: 0, t1: 1, jaw: "no" },
      ],
    });
    expect(parsed?.events).toHaveLength(1);
    expect(parsed?.visemes).toHaveLength(0);
  });
});

describe("createPerformancePlayer", () => {
  it("reports the window jaw while inside a viseme window", () => {
    const player = createPerformancePlayer(TIMELINE);
    expect(player.sample(0.2).mouth).toBeCloseTo(0.9);
    expect(player.sample(0.6).mouth).toBeCloseTo(0.5);
    // The gap between windows closes the mouth.
    expect(player.sample(0.45).mouth).toBe(0);
    // Past the last window the mouth stays closed.
    expect(player.sample(3.5).mouth).toBe(0);
  });

  it("returns null mouth when the timeline has no visemes", () => {
    const player = createPerformancePlayer({ ...TIMELINE, visemes: [] });
    expect(player.sample(0.2).mouth).toBeNull();
  });

  it("layers a gesture clip inside its envelope and nothing outside", () => {
    const player = createPerformancePlayer(TIMELINE);
    const before = player.sample(0.5);
    expect(before.head).toBeNull();
    expect(before.neck).toBeNull();
    const idle = player.sample(2.5);
    expect(idle.head).toBeNull();
    const mid = player.sample(1.6);
    expect(mid.head).not.toBeNull();
    expect(mid.head?.[0]).toBeGreaterThan(0);
    expect(mid.neck?.[0]).toBeGreaterThan(0);
    // After the clip ends the offsets are gone.
    expect(player.sample(2.21).head).toBeNull();
  });

  it("keeps the mouth while a headshake gesture runs", () => {
    const player = createPerformancePlayer(TIMELINE);
    // t=3 has no viseme window, so the mouth closes but the gesture shows.
    const sample = player.sample(3.2);
    expect(sample.mouth).toBe(0);
    expect(sample.head?.[1]).not.toBe(0);
  });

  it("ramp in and out stay within the clip amplitude", () => {
    const player = createPerformancePlayer(TIMELINE);
    const peak = player.sample(1.6).head?.[0] ?? 0;
    const rampIn = player.sample(1.05).head?.[0] ?? 0;
    const rampOut = player.sample(2.15).head?.[0] ?? 0;
    expect(peak).toBeGreaterThan(rampIn);
    expect(peak).toBeGreaterThan(rampOut);
    expect(rampIn).toBeGreaterThanOrEqual(0);
  });

  it("expanded clips move arms inside their envelopes and stop outside", () => {
    const player = createPerformancePlayer({
      ...TIMELINE,
      posture: "",
      events: [
        { t: 0.5, type: "gesture", clip: "both_hands_open", dur: 1.2, fade_ms: 100 },
        { t: 2.2, type: "gesture", clip: "point_raise", dur: 1.0, fade_ms: 100 },
      ],
    });
    const open = player.sample(1.1);
    expect(open.upperArmL).not.toBeNull();
    expect(open.upperArmR).not.toBeNull();
    expect(open.forearmL).not.toBeNull();
    const point = player.sample(2.7);
    expect(point.upperArmR).not.toBeNull();
    expect(point.forearmR).not.toBeNull();
    expect(point.handR).not.toBeNull();
    expect(player.sample(3.5).upperArmR).toBeNull();
    expect(player.sample(3.5).forearmR).toBeNull();
  });

  it("parses every expanded clip name", () => {
    for (const clip of ["head_tilt_think", "hand_chop", "weight_shift"]) {
      const parsed = parsePerformanceTimeline({
        ...TIMELINE,
        events: [{ t: 1, type: "gesture", clip, dur: 1, fade_ms: 100 }],
      });
      expect(parsed?.events).toHaveLength(1);
    }
  });
});
