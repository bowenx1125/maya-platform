import type { Group, RosterEntry } from "./api";

export type GroupSortOrder = "name" | "members";

export const GROUP_SORT_STORAGE_KEY = "maya.accounts.groupSort";

export function parseGroupSort(value: string | null): GroupSortOrder {
  return value === "members" ? "members" : "name";
}

export function byName(left: string, right: string) {
  return left.localeCompare(right, undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

export function countGroupStudents(entries: RosterEntry[]) {
  const counts = new Map<string, number>();
  for (const entry of entries) {
    if (entry.role !== "student" || entry.status === "inactive") continue;
    for (const id of new Set((entry.groups ?? []).map((group) => group.id))) {
      counts.set(id, (counts.get(id) ?? 0) + 1);
    }
  }
  return counts;
}

export function sortGroups(
  groups: Group[],
  counts: ReadonlyMap<string, number>,
  order: GroupSortOrder,
) {
  return [...groups].sort(
    (left, right) =>
      (order === "members"
        ? (counts.get(right.id) ?? 0) - (counts.get(left.id) ?? 0)
        : 0) || byName(left.name, right.name),
  );
}
