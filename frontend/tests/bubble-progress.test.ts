import { describe, expect, it } from "vitest";

import {
  bubbleProgressFrom,
  waitForBubblePaint,
} from "../components/debate-beta/stage/bubble-progress";

describe("Debates (beta) progressive speech bubble", () => {
  it("mounts the first code point at play start and for unknown duration", () => {
    const speech = "Water yields, and so it prevails.";
    expect(bubbleProgressFrom(speech, 0, 10)).toBe("W");
    expect(bubbleProgressFrom(speech, 0, Number.POSITIVE_INFINITY)).toBe("W");
    expect(bubbleProgressFrom(speech, 5, Number.POSITIVE_INFINITY)).toBe("W");
  });

  it("returns empty for invalid time values", () => {
    const speech = "Water yields, and so it prevails.";
    expect(bubbleProgressFrom(speech, -1, 10)).toBe("");
    expect(bubbleProgressFrom(speech, Number.NaN, 10)).toBe("");
    expect(bubbleProgressFrom(speech, Number.POSITIVE_INFINITY, 10)).toBe("");
    expect(bubbleProgressFrom(speech, 5, Number.NaN)).toBe("");
    expect(bubbleProgressFrom(speech, 5, 0)).toBe("");
    expect(bubbleProgressFrom(speech, 5, -3)).toBe("");
  });

  it("returns empty for empty or annotation-only speech", () => {
    expect(bubbleProgressFrom("", 5, 10)).toBe("");
    expect(bubbleProgressFrom("   ", 5, 10)).toBe("");
    expect(
      bubbleProgressFrom("〔经典依据：传世本《道德经》第8章〕", 5, 10),
    ).toBe("");
  });

  it("strips annotations and collapses whitespace like bubbleLineFrom", () => {
    expect(
      bubbleProgressFrom(
        "  A community\n\n removes obstacles.〔经典依据：传世本《道德经》第8章〕  ",
        40,
        40,
      ),
    ).toBe("A community removes obstacles.");
    expect(bubbleProgressFrom("A community removes obstacles.", 20, 40)).toBe(
      "A community rem",
    );
  });

  it("reveals text in approximate proportion to audio progress", () => {
    const speech = "abcdefghijklmnop"; // 16 code points
    expect(bubbleProgressFrom(speech, 4, 16)).toBe("abcd");
    expect(bubbleProgressFrom(speech, 8, 16)).toBe("abcdefgh");
    expect(bubbleProgressFrom(speech, 1, 16)).toBe("a");
  });

  it("reveals the full text at or after the duration", () => {
    const speech = "abcdefghijklmnop";
    expect(bubbleProgressFrom(speech, 16, 16)).toBe(speech);
    expect(bubbleProgressFrom(speech, 30, 16)).toBe(speech);
  });

  it("keeps the most recent 116 code points when the window overflows", () => {
    const speech = "x".repeat(300);
    const line = bubbleProgressFrom(speech, 150, 300);
    expect(line.length).toBe(116);
    expect(line).toBe("x".repeat(116));

    const mixed = "a".repeat(60) + "." + "b".repeat(200);
    const tail = bubbleProgressFrom(mixed, 155, 310);
    expect(tail.length).toBeLessThanOrEqual(116);
    expect(tail.endsWith("b")).toBe(true);
  });

  it("never splits surrogate pairs and counts code points, not UTF-16 units", () => {
    const emoji = "\u{1F600}"; // one code point, two UTF-16 units
    const speech = emoji.repeat(150); // 150 code points
    const tail = bubbleProgressFrom(speech, 120, 150);
    expect(Array.from(tail).length).toBe(116);
    expect(tail.length).toBe(232); // 116 emoji, no split pairs
    tail.split("").forEach((unit) => {
      // Every UTF-16 unit is a high or low surrogate of a complete pair.
      expect(/[\u{D800}-\u{DFFF}]/u.test(unit)).toBe(true);
      expect(/[\u{D800}-\u{DBFF}]/u.test(unit)).not.toBe(
        /[\u{DC00}-\u{DFFF}]/u.test(unit),
      );
    });
    expect(new Intl.Segmenter().segment(tail)).toBeDefined();
    expect(bubbleProgressFrom(speech, 150, 150)).toBe(
      speech.slice(speech.length - 232),
    );
  });

  it("reveals emoji whole during playback", () => {
    const speech = "\u{1F642}".repeat(10);
    // 5 of 10 code points at half time
    expect(bubbleProgressFrom(speech, 5, 10)).toBe("\u{1F642}".repeat(5));
    expect(bubbleProgressFrom(speech, 1, 10)).toBe("\u{1F642}");
    expect(bubbleProgressFrom(speech, 0, 10)).toBe("\u{1F642}");
  });
});

describe("waitForBubblePaint", () => {
  it("resolves after two animation frames", async () => {
    let frames = 0;
    const original = globalThis.requestAnimationFrame;
    globalThis.requestAnimationFrame = ((cb: FrameRequestCallback) => {
      frames += 1;
      return original.call(globalThis, cb);
    }) as typeof requestAnimationFrame;
    try {
      await waitForBubblePaint();
      expect(frames).toBe(2);
    } finally {
      globalThis.requestAnimationFrame = original;
    }
  });
});

