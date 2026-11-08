import { describe, expect, it } from "vitest";
import {
  canPublish,
  isFiniteScore,
  isPublishedLocked,
  quizDraftProblems,
  quizItemGradingProblems,
  withAiGrading,
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
  const rubric = "Mentions decoupling producers from consumers.";

  it("needs nothing extra when AI grading is off", () => {
    expect(quizItemGradingProblems(validText)).toEqual([]);
    const manual = { ...validText, grading: { mode: "manual" as const } };
    expect(quizItemGradingProblems(manual)).toEqual([]);
    expect(quizDraftProblems("Quiz", [validSingle, manual])).toEqual([]);
    expect(canPublish("Quiz", [validSingle, manual])).toBe(true);
  });

  it("grades by the rubric: an empty or short rubric blocks Done", () => {
    for (const text of ["", "  ", "Cite one source."]) {
      const item = {
        ...validText,
        points: 5,
        answer: { rubric: text },
        grading: { mode: "ai" as const },
      };
      expect(quizItemGradingProblems(item).join(" ")).toMatch(/rubric.*20/);
      expect(canPublish("Quiz", [validSingle, item])).toBe(false);
    }
  });

  it("accepts AI grading with a real rubric and no range to fill in", () => {
    const item = {
      ...validText,
      points: 5,
      answer: { rubric },
      grading: { mode: "ai" as const },
    };
    expect(quizItemGradingProblems(item)).toEqual([]);
    expect(canPublish("Quiz", [validSingle, item])).toBe(true);
  });

  it("reads stored rules when an older quiz has no rubric", () => {
    const item = {
      ...validText,
      points: 5,
      grading: { mode: "ai" as const, rules: rubric },
    };
    expect(quizItemGradingProblems(item)).toEqual([]);
  });

  it("sends the backend its rules and 0..points range from the rubric", () => {
    const item = {
      ...validText,
      points: 4,
      answer: { rubric: `  ${rubric}  ` },
      grading: { mode: "ai" as const },
    };
    expect(withAiGrading(item).grading).toEqual({
      mode: "ai",
      score_min: 0,
      score_max: 4,
      rules: rubric,
    });
    expect(withAiGrading(validText)).toEqual(validText);
    expect(
      withAiGrading({ ...validSingle, grading: { mode: "ai" } }).grading,
    ).toBeUndefined();
  });

  it("never invents a score", () => {
    expect(isFiniteScore(undefined)).toBe(false);
    expect(isFiniteScore(null)).toBe(false);
    expect(isFiniteScore(Number.NaN)).toBe(false);
    expect(isFiniteScore(0)).toBe(true);
  });
});
