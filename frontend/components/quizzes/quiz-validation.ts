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

export function quizGradingStatusLabel(
  status: string | null | undefined,
): string {
  if (status === "pending") return "Pending";
  if (status === "mixed") return "Mixed";
  if (status === "complete") return "Complete";
  return "";
}

export function quizItemGradingProblems(item: QuizItemTeacher): string[] {
  if (!isTextItem(item) || item.grading?.mode !== "ai") {
    return [];
  }
  const problems: string[] = [];
  const rules = (item.grading.rules ?? "").trim();
  if (!rules) {
    problems.push("AI grading requires rules.");
  } else if (rules.length < AI_RULES_MIN_LENGTH) {
    problems.push("AI grading rules must be at least 20 characters.");
  }
  const min = item.grading.score_min;
  const max = item.grading.score_max;
  const points = item.points ?? 0;
  const minOk = isFiniteScore(min);
  const maxOk = isFiniteScore(max);
  if (!minOk || !maxOk) {
    problems.push("AI grading requires score min and score max.");
  } else if (min > max) {
    problems.push("Score min must be less than or equal to score max.");
  } else if (min < 0 || max > points) {
    problems.push("Score min and score max must be between 0 and points.");
  }
  return problems;
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
