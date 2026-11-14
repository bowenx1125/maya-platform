"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { TeacherStudyformWorkspace } from "../../../components/teacher-workspace";
import { RouteGuard } from "../../../components/session-provider";
import { LoadingPage } from "../../../components/ui";

function TeacherTeamsRoute() {
  const query = useSearchParams();
  const q = (key: string) => query.get(key) ?? undefined;
  return (
    <RouteGuard role="teacher">
      <TeacherStudyformWorkspace
        view="teams"
        initialGroupId={q("group_id")}
        initialMode={q("mode")}
        initialTeamId={q("team_id")}
      />
    </RouteGuard>
  );
}

/**
 * The teacher's Teams page (sidebar Teams); ?mode=team-new /
 * team-edit&team_id open Create / Edit Team.
 */
// The query (and path) is read in the browser, so following a link here
// needs no server render; only the page's own data requests wait.
export default function TeacherTeamsPage() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <TeacherTeamsRoute />
    </Suspense>
  );
}
