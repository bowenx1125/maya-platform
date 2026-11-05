"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { AppShell } from "../../../components/app-shell";
import { BrainformWorkspace } from "../../../components/knowledge/brainform-workspace";
import { RouteGuard } from "../../../components/session-provider";
import { LoadingPage } from "../../../components/ui";

function StudentRecordRoute() {
  const query = useSearchParams();
  const q = (key: string) => query.get(key) ?? undefined;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <BrainformWorkspace
          role="student"
          recordPage
          initialAgentId={q("agent_id")}
          initialSetId={q("set_id")}
          initialJobId={q("job_id")}
          initialCourseId={q("course_id")}
          initialGroupId={q("group_id")}
          initialMode={q("mode")}
          initialDocumentId={q("document_id")}
        />
      </AppShell>
    </RouteGuard>
  );
}

// The query (and path) is read in the browser, so following a link here
// needs no server render; only the page's own data requests wait.
export default function StudentRecordPage() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <StudentRecordRoute />
    </Suspense>
  );
}
