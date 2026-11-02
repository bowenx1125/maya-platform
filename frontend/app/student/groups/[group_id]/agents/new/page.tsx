"use client";

import { Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";

import { AppShell } from "../../../../../../components/app-shell";
import { CreateAgentForm } from "../../../../../../components/student-workspace";
import { RouteGuard } from "../../../../../../components/session-provider";
import { LoadingPage } from "../../../../../../components/ui";

function NewAgentRoute() {
  const { group_id: groupId } = useParams<{ group_id: string }>();
  const query = useSearchParams();
  const q = (key: string) => query.get(key) ?? undefined;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <CreateAgentForm groupId={groupId} returnHref={q("return")} />
      </AppShell>
    </RouteGuard>
  );
}

// The query (and path) is read in the browser, so following a link here
// needs no server render; only the page's own data requests wait.
export default function NewAgentPage() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <NewAgentRoute />
    </Suspense>
  );
}
