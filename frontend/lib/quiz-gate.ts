/** Student Start is allowed only when taking_open is true. */
export function canStudentStartQuiz(quiz: {
  taking_open?: boolean | null;
}): boolean {
  return quiz.taking_open === true;
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
