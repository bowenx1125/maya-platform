import { describe, expect, it } from "vitest";

import { bubbleLineFrom } from "../components/debate-beta/stage/beta-stage";

describe("Debates (beta) speech bubble", () => {
  it("shows a short turn whole", () => {
    expect(bubbleLineFrom("Water yields, and so it prevails.")).toBe(
      "Water yields, and so it prevails.",
    );
  });

  it("drops the server-appended classic reference before it is spoken", () => {
    expect(
      bubbleLineFrom(
        "A community removes obstacles.〔经典依据：传世本《道德经》第8章〕",
      ),
    ).toBe("A community removes obstacles.");
  });

  it("cuts a long turn at a sentence rather than mid-word", () => {
    const speech =
      "Force applied against the grain of a situation creates the resistance " +
      "it then has to overcome. A community usually accomplishes more by " +
      "removing obstacles than by imposing a plan on it.";
    const line = bubbleLineFrom(speech);
    expect(line.length).toBeLessThanOrEqual(117);
    expect(line.endsWith(".")).toBe(true);
    expect(speech.startsWith(line)).toBe(true);
  });

  it("falls back to an ellipsis when no sentence ends in range", () => {
    const line = bubbleLineFrom("x".repeat(400));
    expect(line.endsWith("…")).toBe(true);
    expect(line.length).toBeLessThanOrEqual(117);
  });

  it("collapses the whitespace a multi-line turn arrives with", () => {
    expect(bubbleLineFrom("  one\n\n  two  ")).toBe("one two");
  });

  it("has nothing to show for an empty speech", () => {
    expect(bubbleLineFrom("")).toBe("");
  });
});
