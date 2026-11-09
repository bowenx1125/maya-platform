"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useSession } from "./session-provider";
import { Button } from "./ui/button";
import { ErrorNotice } from "./ui";
import { teacherEnterInProgress } from "../lib/teacher-visit";

export function TeacherClassBar() {
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
  if (!scope) return null;
  return (
    <div className="mb-6 grid gap-3">
      <div role="group" aria-label="Classes" className="flex flex-wrap gap-3">
        {classes
          .filter((item) => ids.includes(item.id))
          .map((item) => (
            <Button
              key={item.id}
              variant={item.id === ids[0] ? "default" : "neutral"}
              aria-pressed={item.id === ids[0]}
              busy={busy === item.id}
              disabled={busy !== null}
              className="h-auto min-h-11 max-w-full whitespace-normal rounded-[10px] border-[3px] font-body font-extrabold break-words"
              onClick={() => void choose(item.id)}
            >
              {busy === item.id ? (
                <span className="spinner" aria-hidden="true" />
              ) : null}
              {item.name}
            </Button>
          ))}
      </div>
      {error ? <ErrorNotice error={error} /> : null}
    </div>
  );
}
