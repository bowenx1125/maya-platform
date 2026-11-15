/**
 * Bowen is the all-access account: one login, then Maya teacher or a student
 * in Maya1001 / Maya1002. He stays enrolled in both classes. These helpers
 * keep the student identity inside the class chosen at login (the session
 * lists that class first) and preserve the server’s landing-group order.
 */

export type BowenCourse = { course_id: string; role: string };

export type BowenGroup = { id: string; name: string; course_id: string };

type BowenUser = {
  username?: string;
  courses?: readonly BowenCourse[];
} | null;

/**
 * Class for this student session. The server puts the class chosen at login
 * first, and that order is the class.
 */
export function bowenStudentClassId(user: BowenUser): string | undefined {
  if (user?.username !== "bowen") return undefined;
  const studentIds = (user.courses ?? [])
    .filter((membership) => membership.role === "student")
    .map((membership) => membership.course_id);
  return studentIds[0];
}

/** The server orders memberships by saved choice and stable default-group ids. */
export function bowenLandingGroup<T extends BowenGroup>(
  groups: readonly T[],
  classId: string,
): T | undefined {
  return groups.find((group) => group.course_id === classId);
}
