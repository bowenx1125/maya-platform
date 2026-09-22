import { describe, expect, it } from "vitest";

import { parseLocalDebateManifest } from "../lib/local-roundtable";

const turn = {
  character: "老子",
  speaker_id: "Uncle_Fu",
  speech: "自由与责任相辅相成。",
  audio_file: "laozi.wav",
  duration_seconds: 5,
};

describe("local roundtable manifest", () => {
  it("keeps the debate and excludes a separate voice sample", () => {
    const result = parseLocalDebateManifest({
      topic: "自由与责任",
      turns: [
        turn,
        { ...turn, character: "柏拉图", audio_file: "plato.wav" },
        { ...turn, kind: "sample", audio_file: "woman.wav" },
      ],
    });
    expect(result.turns).toHaveLength(2);
  });

  it("rejects paths and incomplete debate manifests", () => {
    expect(() =>
      parseLocalDebateManifest({ topic: "自由", turns: [turn] }),
    ).toThrow();
    expect(() =>
      parseLocalDebateManifest({
        topic: "自由",
        turns: [turn, { ...turn, audio_file: "../private.wav" }],
      }),
    ).toThrow();
  });

  it("accepts a five-speaker rehearsal", () => {
    const result = parseLocalDebateManifest({
      topic: "课堂辩论",
      turns: Array.from({ length: 5 }, (_, index) => ({
        ...turn,
        character: `人物${index + 1}`,
        audio_file: `speaker-${index + 1}.wav`,
      })),
    });
    expect(result.turns).toHaveLength(5);
  });
});
