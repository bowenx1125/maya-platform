import { describe, expect, it } from "vitest";

import {
  collapseMentionOnBackspace,
  insertedMentionAt,
} from "../lib/mention-insert";
import { mentionedMembers } from "../lib/mention-parse";

const members = [
  { id: "g", name: "Guider" },
  { id: "s", name: "Scorer" },
  { id: "s2", name: "Scorer Pro" },
  { id: "x", name: "Summarizer", available: false },
];

describe("mentionedMembers", () => {
  it("matches the longest member name with no space after it", () => {
    expect(
      mentionedMembers("@Scorer你是干嘛的", members).map((m) => m.id),
    ).toEqual(["s"]);
    expect(
      mentionedMembers("@Scorer Pro hi", members).map((m) => m.id),
    ).toEqual(["s2"]);
  });

  it("ignores unknown or unavailable names so default rules apply", () => {
    expect(mentionedMembers("@Nobody 你好", members)).toEqual([]);
    expect(mentionedMembers("@Summarizer 你好", members)).toEqual([]);
    expect(mentionedMembers("@All 你好", members)).toEqual([]);
    expect(mentionedMembers("```\n@Guider\n``` x", members)).toEqual([]);
  });

  it("keeps first-mention order and de-duplicates", () => {
    expect(
      mentionedMembers("@Scorer and @Guider and @Scorer", members).map(
        (m) => m.id,
      ),
    ).toEqual(["s", "g"]);
  });
});

describe("collapseMentionOnBackspace", () => {
  it("removes the auto space and the name, leaving @", () => {
    const inserted = insertedMentionAt("hi @Sc", "Scorer");
    expect(inserted).toEqual({ at: 3, label: "Scorer" });
    expect(collapseMentionOnBackspace("hi @Scorer ", 11, inserted)).toEqual({
      next: "hi @",
      caret: 4,
    });
    expect(collapseMentionOnBackspace("hi @Scorer more", 11, inserted)).toEqual(
      {
        next: "hi @more",
        caret: 4,
      },
    );
  });

  it("leaves ordinary deletion alone", () => {
    const inserted = { at: 0, label: "Scorer" };
    expect(collapseMentionOnBackspace("@Scorer x", 9, inserted)).toBeNull();
    expect(collapseMentionOnBackspace("@Scorer ", 8, null)).toBeNull();
    expect(collapseMentionOnBackspace("@Scorex ", 8, inserted)).toBeNull();
  });
});
