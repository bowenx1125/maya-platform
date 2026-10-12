// Accounts starts leaving a teacher visit as soon as the roster is open.
// Enter has to wait for that leave, or the delete lands after the new join
// and the group page never sees a membership.
let settledLeaves: Promise<void> = Promise.resolve();
let entering = false;

export function trackTeacherLeave(work: Promise<unknown>): void {
  settledLeaves = settledLeaves
    .then(
      () => work,
      () => work,
    )
    .then(
      () => undefined,
      () => undefined,
    );
}

export function teacherLeavesSettled(): Promise<void> {
  return settledLeaves;
}

export function beginTeacherEnter(): void {
  entering = true;
}

export function endTeacherEnter(): void {
  entering = false;
}

export function teacherEnterInProgress(): boolean {
  return entering;
}
