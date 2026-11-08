import type { QuizItemTeacher } from "@/lib/api/quiz";

const CHOICE_TYPES = new Set(["single", "multiple"]);
const TEXT_TYPES = new Set(["short_text", "long_text"]);
const AI_RULES_MIN_LENGTH = 20;

function isChoiceItem(item: QuizItemTeacher): boolean {
  return CHOICE_TYPES.has(item.type);
}

function isTextItem(item: QuizItemTeacher): boolean {
  return TEXT_TYPES.has(item.type);
}

export function isFiniteScore(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * AI grading scores against the item's rubric within 0..points (the editor
 * fills the contract's rules and range from them), so the only thing a
 * teacher can get wrong is a rubric too short to grade by.
 */
export function quizItemGradingProblems(item: QuizItemTeacher): string[] {
  if (!isTextItem(item) || item.grading?.mode !== "ai") {
    return [];
  }
  const rubric = (item.answer?.rubric ?? item.grading.rules ?? "").trim();
  if (rubric.length < AI_RULES_MIN_LENGTH) {
    return [
      `AI grading needs a grading rubric of at least ${AI_RULES_MIN_LENGTH} characters.`,
    ];
  }
  return [];
}

/**
 * AI grading reads the rubric the teacher already wrote and scores within
 * 0..points, so the editor asks for one switch, not a second rules box and
 * a range (the backend contract still receives all three).
 */
export function withAiGrading(item: QuizItemTeacher): QuizItemTeacher {
  if (isChoiceItem(item) || item.grading?.mode !== "ai") {
    return isChoiceItem(item) ? { ...item, grading: undefined } : item;
  }
  return {
    ...item,
    grading: {
      mode: "ai",
      score_min: 0,
      score_max: item.points ?? 1,
      rules: (item.answer?.rubric ?? "").trim(),
    },
  };
}

function itemProblems(item: QuizItemTeacher): string[] {
  const problems: string[] = [];
  if (!item.prompt.trim()) {
    problems.push("Every question needs a prompt.");
  }
  if (isChoiceItem(item) && item.choices.length < 1) {
    problems.push("Choice questions need at least one choice.");
  }
  problems.push(...quizItemGradingProblems(item));
  return problems;
}

/** Validation for editing/saving a quiz draft. */
export function quizDraftProblems(
  title: string,
  items: QuizItemTeacher[],
): string[] {
  const problems: string[] = [];
  if (!title.trim()) {
    problems.push("Title is required.");
  }
  if (items.length < 1) {
    problems.push("Add at least one question.");
  }
  for (const item of items) {
    problems.push(...itemProblems(item));
  }
  return problems;
}

/** Extra requirements on top of a valid draft before the quiz may be published. */
export function canPublish(title: string, items: QuizItemTeacher[]): boolean {
  if (quizDraftProblems(title, items).length > 0) {
    return false;
  }
  return items.every((item) => {
    if (!isChoiceItem(item)) return true;
    const ids = item.answer?.choice_ids ?? [];
    return ids.length > 0;
  });
}

/** Published quizzes are locked for structural edits. */
export function isPublishedLocked(status: string): boolean {
  return status === "published";
}
