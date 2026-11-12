/**
 * Bowen is the all-access account: one login, then Maya teacher or a student
 * in Maya1001 / Maya1002. He stays enrolled in both classes. These helpers
 * keep the student identity inside the class chosen at login (the session
 * lists that class first) and out of the protected Students shell when the
 * class has a real group.
 */

const LAST_CLASS_KEY = "maya.bowen.student-class";

export type BowenCourse = { course_id: string; role: string };

export type BowenGroup = { id: string; name: string; course_id: string };

type BowenUser = {
  username?: string;
  courses?: readonly BowenCourse[];
} | null;

/** The protected class shell. A group a student named "Students" is treated the same. */
export function isProtectedStudentsShell(name: string): boolean {
  return name === "Students";
}

export function rememberBowenStudentClass(courseId: string): void {
  try {
    window.localStorage.setItem(LAST_CLASS_KEY, courseId);
  } catch {
    // Private mode: the session's course order still names the class.
  }
}

export function readBowenStudentClass(): string | null {
  try {
    return window.localStorage.getItem(LAST_CLASS_KEY);
  } catch {
    return null;
  }
}

/**
 * Class for this student session. The server puts the class chosen at login
 * first; that choice wins and is what we remember. A stored id is only a
 * record of that choice, not a second source that can disagree with it.
 */
export function bowenStudentClassId(user: BowenUser): string | undefined {
  if (user?.username !== "bowen") return undefined;
  const studentIds = (user.courses ?? [])
    .filter((membership) => membership.role === "student")
    .map((membership) => membership.course_id);
  return studentIds[0];
}

/**
 * First group of `classId` in the order given (the order the home already
 * lists memberships), skipping the Students shell when the class has another
 * group. The shell is used only when it is the class's only group.
 */
export function bowenLandingGroup<T extends BowenGroup>(
  groups: readonly T[],
  classId: string,
): T | undefined {
  const inClass = groups.filter((group) => group.course_id === classId);
  const open = inClass.filter((group) => !isProtectedStudentsShell(group.name));
  return (open.length ? open : inClass)[0];
}
