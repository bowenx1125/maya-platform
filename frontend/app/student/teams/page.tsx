"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { AppShell } from "../../../components/app-shell";
import { StudentTeamsPage } from "../../../components/student-workspace";
import { RouteGuard } from "../../../components/session-provider";
import { LoadingPage } from "../../../components/ui";

function StudentTeamsRoute() {
  const query = useSearchParams();
  const q = (key: string) => query.get(key) ?? undefined;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <StudentTeamsPage
          groupId={q("group_id")}
          mode={q("mode")}
          teamId={q("team_id")}
        />
      </AppShell>
    </RouteGuard>
  );
}

/**
 * A group's Teams page (sidebar Teams); ?group_id picks the group and
 * ?mode=team-new / team-edit&team_id open Create / Edit Team.
 */
// The query (and path) is read in the browser, so following a link here
// needs no server render; only the page's own data requests wait.
export default function TeamsRoute() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <StudentTeamsRoute />
    </Suspense>
  );
}
