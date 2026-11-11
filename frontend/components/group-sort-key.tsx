"use client";

import type { GroupSortOrder } from "../lib/group-sort";
import { PRESS_MOTION } from "./ui/button";
import styles from "./roster-workspace.module.css";

export function GroupSortKey({
  order,
  onChange,
}: {
  order: GroupSortOrder;
  onChange: (order: GroupSortOrder) => void;
}) {
  const label = order === "members" ? "Most members" : "A–Z";
  return (
    <div className={styles.groupSort}>
      <button
        type="button"
        className={`${styles.sortKey} ${PRESS_MOTION}`}
        aria-label={`Sort groups: ${label}`}
        data-testid="group-sort"
        onClick={() => onChange(order === "name" ? "members" : "name")}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M8 4v16m-4-4 4 4 4-4M16 20V4m-4 4 4-4 4 4" />
        </svg>
        <span>{label}</span>
      </button>
    </div>
  );
}

export function GroupStudentCount({ count }: { count: number }) {
  return (
    <span
      className={styles.studentCount}
      data-testid="group-student-count"
      role="img"
      aria-label={`${count} ${count === 1 ? "student" : "students"}`}
    >
      <svg
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
      >
        <circle cx="12" cy="7" r="4" />
        <path d="M5 21v-2a7 7 0 0 1 14 0v2" />
      </svg>
      <span>{count}</span>
    </span>
  );
}
