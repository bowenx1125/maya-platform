"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { TeacherStudyformWorkspace } from "../../../components/teacher-workspace";
import { RouteGuard } from "../../../components/session-provider";
import { LoadingPage } from "../../../components/ui";

function TeacherAgentsRoute() {
  const query = useSearchParams();
  const q = (key: string) => query.get(key) ?? undefined;
  return (
    <RouteGuard role="teacher">
      <TeacherStudyformWorkspace view="agents" initialGroupId={q("group_id")} />
    </RouteGuard>
  );
}

/** The teacher's Agents page (sidebar Agents). */
// The query (and path) is read in the browser, so following a link here
// needs no server render; only the page's own data requests wait.
export default function TeacherAgentsPage() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <TeacherAgentsRoute />
    </Suspense>
  );
}
