import { describe, expect, it } from "vitest";

import {
  formatQuizTime,
  fromDatetimeLocal,
  toDatetimeLocal,
} from "../lib/quiz-time";

describe("quiz time (UTC+8)", () => {
  it("formats and round-trips a UTC instant", () => {
    const iso = "2026-11-12T10:00:00.000Z";
    expect(formatQuizTime(iso)).toBe("Nov 12, 18:00");
    expect(toDatetimeLocal(iso)).toBe("2026-11-12T18:00");
    expect(fromDatetimeLocal("2026-11-12T18:00")).toBe(iso);
  });

  it("rejects an incomplete local value", () => {
    expect(fromDatetimeLocal("2026-11-12")).toBeNull();
    expect(fromDatetimeLocal("")).toBeNull();
  });
});
