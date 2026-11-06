/** Student Start is allowed only after the teacher starts evaluation. */
export function canStudentStartQuiz(quiz: {
  accepting_submissions?: boolean | null;
}): boolean {
  return quiz.accepting_submissions === true;
}

/**
 * In-flight Done/publish lock. Returns false when a publish is already
 * running so a double/triple click cannot create multiple quizzes.
 */
export function beginDoneLock(lock: { current: boolean }): boolean {
  if (lock.current) return false;
  lock.current = true;
  return true;
}

export function releaseDoneLock(lock: { current: boolean }): void {
  lock.current = false;
}
