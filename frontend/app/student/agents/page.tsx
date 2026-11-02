"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { AppShell } from "../../../components/app-shell";
import { StudentAgentsPage } from "../../../components/student-workspace";
import { RouteGuard } from "../../../components/session-provider";
import { LoadingPage } from "../../../components/ui";

function AgentsRoute() {
  const query = useSearchParams();
  const q = (key: string) => query.get(key) ?? undefined;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <StudentAgentsPage groupId={q("group_id")} />
      </AppShell>
    </RouteGuard>
  );
}

/** A group's Agents page (sidebar Agents); ?group_id picks the group. */
// The query (and path) is read in the browser, so following a link here
// needs no server render; only the page's own data requests wait.
export default function AgentsPage() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <AgentsRoute />
    </Suspense>
  );
}
