import { describe, expect, it, vi } from "vitest";

import { applyMentionInsert, placeMentionCaret } from "../lib/mention-insert";

describe("applyMentionInsert", () => {
  it.each([
    ["Maya", "", "@Maya "],
    ["Bowen", "", "@Bowen "],
    ["Jade", "hello ", "hello @Jade "],
    ["Guide", "@", "@Guide "],
    ["Scorer", "ask @Sc", "ask @Scorer "],
    ["A", "x @partial more", "x @A more"],
  ])(
    "inserts @%s with a single trailing space (%j → %j)",
    (label, draft, expected) => {
      const { next, caret } = applyMentionInsert(draft, label);
      expect(next).toBe(expected);
      expect(next.slice(caret - 1, caret)).toBe(" ");
      expect(caret).toBe(next.indexOf(`@${label}`) + label.length + 2);
    },
  );

  it("does not add a second space when one already follows the token", () => {
    const { next, caret } = applyMentionInsert("@Ma 喜欢你", "Maya");
    expect(next).toBe("@Maya 喜欢你");
    expect(caret).toBe("@Maya ".length);
    expect(next.slice(caret)).toBe("喜欢你");
  });

  it("replaces only the incomplete token after the last @", () => {
    const { next, caret } = applyMentionInsert("hi @Old and @Ne", "NewAgent");
    expect(next).toBe("hi @Old and @NewAgent ");
    expect(caret).toBe(next.length);
  });

  it("keeps mention parsing: name stops at the trailing space", () => {
    const { next } = applyMentionInsert("@", "Bowen");
    expect(next).toBe("@Bowen ");
    const labels = [...next.matchAll(/@([^\s@]+)/g)].map((m) => m[1]);
    expect(labels).toEqual(["Bowen"]);
  });

  it("works for Chinese continuation text after the space", () => {
    const { next, caret } = applyMentionInsert("@", "Bowen");
    const continued = `${next.slice(0, caret)}我喜欢你${next.slice(caret)}`;
    expect(continued).toBe("@Bowen 我喜欢你");
    expect([...continued.matchAll(/@([^\s@]+)/g)].map((m) => m[1])).toEqual([
      "Bowen",
    ]);
  });
});

describe("placeMentionCaret", () => {
  it("focuses the element and places the caret", () => {
    const el = {
      focus: vi.fn(),
      setSelectionRange: vi.fn(),
    } as unknown as HTMLTextAreaElement;
    placeMentionCaret(el, 7);
    expect(el.focus).toHaveBeenCalledTimes(1);
    expect(el.setSelectionRange).toHaveBeenCalledWith(7, 7);
  });

  it("no-ops when the element is missing", () => {
    expect(() => placeMentionCaret(null, 0)).not.toThrow();
  });
});
