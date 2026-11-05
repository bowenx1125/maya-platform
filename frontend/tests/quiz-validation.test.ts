import { describe, expect, it } from "vitest";
import {
  canPublish,
  isPublishedLocked,
  quizDraftProblems,
} from "../components/quizzes/quiz-validation";
import type { QuizItemTeacher } from "../lib/api/quiz";

function choice(id: string, label: string) {
  return { id, label };
}

function makeItem(partial: Partial<QuizItemTeacher> & Pick<QuizItemTeacher, "id" | "type">): QuizItemTeacher {
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
    expect(quizDraftProblems("Quiz", [validSingle, bad]).length).toBeGreaterThan(0);
  });

  it("flags a choice item with zero choices", () => {
    const bad = makeItem({
      id: "z1",
      type: "single",
      prompt: "Pick",
      choices: [],
      answer: { choice_ids: [] },
    });
    expect(quizDraftProblems("Quiz", [validText, bad]).length).toBeGreaterThan(0);
  });

  it("accepts a fully valid draft", () => {
    expect(quizDraftProblems("Quiz", [validSingle, validMultiple, validText])).toEqual([]);
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
    expect(canPublish("Quiz", [validSingle, validMultiple, validText])).toBe(true);
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
