"use client";

import { useEffect, useState } from "react";

import {
  bowenLandingGroup,
  bowenStudentClassId,
  rememberBowenStudentClass,
  type BowenGroup,
} from "../lib/bowen-student";
import { useSession } from "./session-provider";

/**
 * The group Bowen should open as a student: first non-Students group of the
 * class chosen at login. Other students do not use this.
 */
export function useBowenLandingGroupId(): {
  ready: boolean;
  groupId: string | null;
} {
  const { api, user } = useSession();
  const classId = bowenStudentClassId(user);
  const ids = (user?.groups ?? [])
    .map((membership) => membership.group_id)
    .join(",");
  const key = `${classId ?? ""}:${ids}`;
  const [state, setState] = useState<{
    key: string;
    groupId: string | null;
  } | null>(null);

  useEffect(() => {
    if (user?.username !== "bowen" || !classId) return;
    rememberBowenStudentClass(classId);
    let active = true;
    const groupIds = ids ? ids.split(",") : [];
    void Promise.all(
      groupIds.map((groupId) => api.group(groupId) as Promise<BowenGroup>),
    )
      .then((groups) => {
        if (!active) return;
        setState({
          key,
          groupId: bowenLandingGroup(groups, classId)?.id ?? null,
        });
      })
      .catch(() => {
        if (active) setState({ key, groupId: null });
      });
    return () => {
      active = false;
    };
  }, [api, classId, ids, key, user?.username]);

  if (user?.username !== "bowen" || !classId)
    return { ready: true, groupId: null };
  if (!state || state.key !== key) return { ready: false, groupId: null };
  return { ready: true, groupId: state.groupId };
}
