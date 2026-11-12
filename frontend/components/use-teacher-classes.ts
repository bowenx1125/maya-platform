"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useSession } from "./session-provider";
import { teacherEnterInProgress } from "../lib/teacher-visit";

export function useTeacherClasses() {
  const { api, user, selectTeacherCourse } = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const ids = (user?.courses ?? [])
    .filter((item) => item.role === "teacher")
    .map((item) => item.course_id);
  const scope = ids.join(",");
  const [classes, setClasses] = useState<{ id: string; name: string }[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let active = true;
    if (scope && typeof api.courses === "function")
      void api
        .courses()
        .then((items) => {
          if (active)
            setClasses(
              items.filter((item) => scope.split(",").includes(item.id)),
            );
        })
        .catch((cause) => {
          if (active) setError(cause);
        });
    return () => {
      active = false;
    };
  }, [api, scope]);
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
