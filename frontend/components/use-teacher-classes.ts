"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useSession } from "./session-provider";
import { teacherEnterInProgress } from "../lib/teacher-visit";

type ClassList = { id: string; name: string }[];
type ClassSnapshot = { key: string; classes: ClassList };
// The session API survives route and stage transitions; never share labels
// between accounts or different teacher memberships.
const snapshots = new WeakMap<object, ClassSnapshot>();

export function useTeacherClasses() {
  const { api, user, selectTeacherCourse } = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const ids = (user?.courses ?? [])
    .filter((item) => item.role === "teacher")
    .map((item) => item.course_id);
  const scope = ids.join(",");
  const key = JSON.stringify([user?.id, [...ids].sort()]);
  const cached = snapshots.get(api);
  const [snapshot, setSnapshot] = useState<ClassSnapshot | undefined>(() =>
    cached?.key === key ? cached : undefined,
  );
  const classes =
    (snapshot?.key === key
      ? snapshot
      : cached?.key === key
        ? cached
        : undefined
    )?.classes ?? [];
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let active = true;
    if (scope && typeof api.courses === "function")
      void api
        .courses()
        .then((items) => {
          if (active) {
            const next = {
              key,
              classes: items.filter((item) =>
                scope.split(",").includes(item.id),
              ),
            };
            snapshots.set(api, next);
            setSnapshot(next);
          }
        })
        .catch((cause) => {
          if (active) setError(cause);
        });
    return () => {
      active = false;
    };
  }, [api, scope, key]);
  async function choose(id: string) {
    if (busy || id === ids[0] || teacherEnterInProgress()) return;
    setBusy(id);
    setError(null);
    try {
      await selectTeacherCourse(id);
      // Detail URLs and group visits belong to the old class; open the same
      // module's list in the new scope instead of retaining those identifiers.
      const section = pathname.match(
        /^\/teacher\/(agents|teams|knowledge|rag|voices|record|debates|chat|roster|quizzes)(?:\/|$)/,
      )?.[1];
      const kind = new URLSearchParams(window.location.search).get("kind");
      router.replace(
        section
          ? `/teacher/${section}${section === "chat" && kind === "team" ? "?kind=team" : ""}`
          : "/teacher",
      );
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
    }
  }
  return {
    classes: classes.filter((item) => ids.includes(item.id)),
    current: classes.find((item) => item.id === ids[0]),
    multiple: ids.length > 1,
    busy,
    error,
    choose,
  };
}
