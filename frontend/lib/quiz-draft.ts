/**
 * Take-a-quiz draft persistence (Quiz M4). One localStorage key per
 * course/user/quiz so a refresh never loses answers; every read/write
 * tolerates a missing or refusing localStorage (SSR, private mode).
 */

export type QuizDraftAnswer = { choice_ids?: string[]; text?: string };
export type QuizDraft = Record<string, QuizDraftAnswer>;

/** Exact key format: quiz-draft:{courseId}:{userId}:{quizId}. */
export function quizDraftKey(
  courseId: string,
  userId: string,
  quizId: string,
): string {
  return `quiz-draft:${courseId}:${userId}:${quizId}`;
}

export function readQuizDraft(
  courseId: string,
  userId: string,
  quizId: string,
): QuizDraft | null {
  try {
    const raw = window.localStorage.getItem(
      quizDraftKey(courseId, userId, quizId),
    );
    if (!raw) return null;
    const parsed = JSON.parse(raw) as QuizDraft;
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export function writeQuizDraft(
  courseId: string,
  userId: string,
  quizId: string,
  draft: QuizDraft,
): void {
  try {
    window.localStorage.setItem(
      quizDraftKey(courseId, userId, quizId),
      JSON.stringify(draft),
    );
  } catch {
    // Memory-only for this page; the answers still submit.
  }
}

export function clearQuizDraft(
  courseId: string,
  userId: string,
  quizId: string,
): void {
  try {
    window.localStorage.removeItem(quizDraftKey(courseId, userId, quizId));
  } catch {
    // Nothing to recover; the server holds the submitted attempt.
  }
}

/** The Records tab deep link; the old /student/record redirects here (M4). */
export const QUIZ_RECORDS_PATH = "/student/quiz?tab=records";
