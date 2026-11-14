"use client";

import { Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";

import { RouteGuard } from "../../../../components/session-provider";
import { TeacherAgentDetail } from "../../../../components/teacher-workspace";
import { LoadingPage } from "../../../../components/ui";

function TeacherAgentRoute() {
  const { agent_id: agentId } = useParams<{ agent_id: string }>();
  const query = useSearchParams();
  const q = (key: string) => query.get(key) ?? undefined;
  return (
    <RouteGuard role="teacher">
      <TeacherAgentDetail
        agentId={agentId}
        snapshotId={q("snapshot")}
        generationFlow={q("flow") === "ai-knowledge"}
        generationSetId={q("update_set_id")}
      />
    </RouteGuard>
  );
}

// The query (and path) is read in the browser, so following a link here
// needs no server render; only the page's own data requests wait.
export default function TeacherAgentPage() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <TeacherAgentRoute />
    </Suspense>
  );
}
