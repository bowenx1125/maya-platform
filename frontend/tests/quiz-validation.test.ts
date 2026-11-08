import { describe, expect, it } from "vitest";
import {
  canPublish,
  isFiniteScore,
  isPublishedLocked,
  quizDraftProblems,
  quizGradingStatusLabel,
  quizItemGradingProblems,
} from "../components/quizzes/quiz-validation";
import type { QuizItemTeacher } from "../lib/api/quiz";

function choice(id: string, label: string) {
  return { id, label };
}

function makeItem(
  partial: Partial<QuizItemTeacher> & Pick<QuizItemTeacher, "id" | "type">,
): QuizItemTeacher {
  return { prompt: "What?", choices: [], answer: null, ...partial };
}

const validSingle = makeItem({
  id: "s1",
  type: "single",
  prompt: "Pick one",
  choices: [choice("c1", "A"), choice("c2", "B")],
  answer: { choice_ids: ["c1"] },
});

const validMultiple = makeItem({
  id: "m1",
  type: "multiple",
  prompt: "Pick many",
  choices: [choice("c3", "X"), choice("c4", "Y")],
  answer: { choice_ids: ["c3", "c4"] },
});

const validText = makeItem({
  id: "t1",
  type: "short_text",
  prompt: "Explain",
});

describe("quizDraftProblems", () => {
  it("flags an empty title", () => {
    expect(quizDraftProblems("  ", [validSingle]).length).toBeGreaterThan(0);
  });

  it("flags a draft with no items", () => {
    expect(quizDraftProblems("Quiz", []).length).toBeGreaterThan(0);
  });

  it("flags an item with an empty prompt", () => {
    const bad = makeItem({ id: "p1", type: "short_text", prompt: "   " });
    expect(
      quizDraftProblems("Quiz", [validSingle, bad]).length,
    ).toBeGreaterThan(0);
  });

  it("flags a choice item with zero choices", () => {
    const bad = makeItem({
      id: "z1",
      type: "single",
      prompt: "Pick",
      choices: [],
      answer: { choice_ids: [] },
    });
    expect(quizDraftProblems("Quiz", [validText, bad]).length).toBeGreaterThan(
      0,
    );
  });

  it("accepts a fully valid draft", () => {
    expect(
      quizDraftProblems("Quiz", [validSingle, validMultiple, validText]),
    ).toEqual([]);
  });
});

describe("canPublish", () => {
  it("is false when the draft has problems", () => {
    expect(canPublish("", [validSingle])).toBe(false);
    expect(canPublish("Quiz", [])).toBe(false);
  });

  it("is false when a choice item has empty choice_ids in its answer", () => {
    const noAnswer = makeItem({
      id: "na1",
      type: "multiple",
      prompt: "Pick",
      choices: [choice("c1", "A"), choice("c2", "B")],
      answer: { choice_ids: [] },
    });
    expect(canPublish("Quiz", [validText, noAnswer])).toBe(false);
  });

  it("is true when single/multiple items have answers and text items are fine", () => {
    expect(canPublish("Quiz", [validSingle, validMultiple, validText])).toBe(
      true,
    );
  });
});

describe("isPublishedLocked", () => {
  it("locks a published quiz", () => {
    expect(isPublishedLocked("published")).toBe(true);
  });

  it("does not lock a draft quiz", () => {
    expect(isPublishedLocked("draft")).toBe(false);
  });
});

describe("AI grading validation", () => {
  const longRules = "Cite at least one source.";

  it("does not require range or rules when AI grading is off", () => {
    expect(quizItemGradingProblems(validText)).toEqual([]);
    expect(
      quizItemGradingProblems({
        ...validText,
        grading: { mode: "manual" },
      }),
    ).toEqual([]);
    expect(
      quizDraftProblems("Quiz", [
        validSingle,
        { ...validText, grading: { mode: "manual" } },
      ]),
    ).toEqual([]);
    expect(
      canPublish("Quiz", [
        validSingle,
        { ...validText, grading: { mode: "manual" } },
      ]),
    ).toBe(true);
  });

  it("blocks empty rules when AI grading is on", () => {
    const item = {
      ...validText,
      points: 5,
      grading: { mode: "ai" as const, score_min: 0, score_max: 5, rules: "  " },
    };
    expect(quizItemGradingProblems(item).join(" ")).toMatch(/rules/i);
    expect(canPublish("Quiz", [validSingle, item])).toBe(false);
  });

  it("blocks rules shorter than 20 characters when AI grading is on", () => {
    const item = {
      ...validText,
      points: 5,
      grading: {
        mode: "ai" as const,
        score_min: 0,
        score_max: 5,
        rules: "Cite one source.",
      },
    };
    expect(quizItemGradingProblems(item).join(" ")).toMatch(/20/);
    expect(canPublish("Quiz", [validSingle, item])).toBe(false);
  });

  it("blocks missing or invalid score range when AI grading is on", () => {
    const base = {
      ...validText,
      points: 5,
      grading: {
        mode: "ai" as const,
        score_min: 0,
        score_max: 5,
        rules: longRules,
      },
    };
    expect(quizItemGradingProblems(base)).toEqual([]);
    expect(
      quizItemGradingProblems({
        ...base,
        grading: { mode: "ai", rules: longRules },
      }),
    ).not.toEqual([]);
    expect(
      quizItemGradingProblems({
        ...base,
        grading: {
          mode: "ai",
          score_min: 4,
          score_max: 1,
          rules: longRules,
        },
      }).join(" "),
    ).toMatch(/score min/i);
    expect(
      quizItemGradingProblems({
        ...base,
        grading: {
          mode: "ai",
          score_min: -1,
          score_max: 5,
          rules: longRules,
        },
      }).join(" "),
    ).toMatch(/points/i);
    expect(
      quizItemGradingProblems({
        ...base,
        grading: {
          mode: "ai",
          score_min: 0,
          score_max: 9,
          rules: longRules,
        },
      }).join(" "),
    ).toMatch(/points/i);
    expect(
      quizItemGradingProblems({
        ...base,
        grading: {
          mode: "ai",
          score_min: Number.NaN,
          score_max: 5,
          rules: longRules,
        },
      }),
    ).not.toEqual([]);
  });

  it("labels grading status without inventing a score", () => {
    expect(quizGradingStatusLabel("pending")).toBe("Pending");
    expect(quizGradingStatusLabel("mixed")).toBe("Mixed");
    expect(quizGradingStatusLabel("complete")).toBe("Complete");
    expect(isFiniteScore(undefined)).toBe(false);
    expect(isFiniteScore(null)).toBe(false);
    expect(isFiniteScore(0)).toBe(true);
    expect(isFiniteScore(4)).toBe(true);
  });
});
