/** Quiz request paths (frontend/lib/api/platform.ts builds these inline). */

export function listCourseQuizzesPath(courseId: string): string {
  return `courses/${encodeURIComponent(courseId)}/quizzes`;
}

export function getStudentQuizPath(courseId: string, quizId: string): string {
  return `courses/${encodeURIComponent(courseId)}/quizzes/${encodeURIComponent(quizId)}`;
}

export function submitQuizAttemptPath(
  courseId: string,
  quizId: string,
): string {
  return `courses/${encodeURIComponent(courseId)}/quizzes/${encodeURIComponent(quizId)}/attempts`;
}

export function listMyRecordAttemptsPath(courseId: string): string {
  return `courses/${encodeURIComponent(courseId)}/my-record-attempts`;
}

export function listCourseRecordAttemptsPath(
  courseId: string,
  quizId?: string,
): string {
  const base = `courses/${encodeURIComponent(courseId)}/record-attempts`;
  if (!quizId) return base;
  return `${base}?quiz_id=${encodeURIComponent(quizId)}`;
}

export function startTakingPath(courseId: string, quizId: string): string {
  return `courses/${encodeURIComponent(courseId)}/quizzes/${encodeURIComponent(quizId)}/start-taking`;
}

export function pauseTakingPath(courseId: string, quizId: string): string {
  return `courses/${encodeURIComponent(courseId)}/quizzes/${encodeURIComponent(quizId)}/pause-taking`;
}

export function exportQuizAttemptsPath(
  courseId: string,
  quizId: string,
): string {
  return `courses/${encodeURIComponent(courseId)}/quizzes/${encodeURIComponent(quizId)}/attempts/export`;
}

/** Banner Download shows only when Records is scoped to one quiz. */
export function shouldShowExportDownload(
  quizId: string | null | undefined,
): boolean {
  return Boolean(quizId && quizId.trim());
}
