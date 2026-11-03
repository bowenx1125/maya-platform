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

// A visit lasts 2 hours on the server (TEACHER_GROUP_VISIT_TTL) and entering
// again renews it. A teacher still inside renews well before that, so a
// lesson longer than 2 hours does not end the visit under them.
export const VISIT_RENEW_MS = 20 * 60_000;
const renewedAt = new Map<string, number>();

export function noteVisitRenewed(groupId: string, at = Date.now()): void {
  renewedAt.set(groupId, at);
}

export function visitRenewalDue(groupId: string, now = Date.now()): boolean {
  const last = renewedAt.get(groupId);
  return last === undefined || now - last >= VISIT_RENEW_MS;
}

export function forgetVisitRenewal(groupId: string): void {
  renewedAt.delete(groupId);
}
