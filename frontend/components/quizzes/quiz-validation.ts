import type { QuizItemTeacher } from "@/lib/api/quiz";

const CHOICE_TYPES = new Set(["single", "multiple"]);

function isChoiceItem(item: QuizItemTeacher): boolean {
  return CHOICE_TYPES.has(item.type);
}

function itemProblems(item: QuizItemTeacher): string[] {
  const problems: string[] = [];
  if (!item.prompt.trim()) {
    problems.push("Every question needs a prompt.");
  }
  if (isChoiceItem(item) && item.choices.length < 1) {
    problems.push("Choice questions need at least one choice.");
  }
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
