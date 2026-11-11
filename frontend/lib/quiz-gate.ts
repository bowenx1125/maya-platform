/** Student Start follows the per-viewer can_take_now flag. */
export function canStudentStartQuiz(quiz: {
  can_take_now?: boolean | null;
  taking_open?: boolean | null;
}): boolean {
  if (quiz.can_take_now !== undefined && quiz.can_take_now !== null) {
    return quiz.can_take_now === true;
  }
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
