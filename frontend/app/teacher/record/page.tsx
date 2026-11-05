"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { AppShell } from "../../../components/app-shell";
import { BrainformWorkspace } from "../../../components/knowledge/brainform-workspace";
import { RouteGuard } from "../../../components/session-provider";
import { LoadingPage } from "../../../components/ui";

function TeacherRecordRoute() {
  const query = useSearchParams();
  const q = (key: string) => query.get(key) ?? undefined;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <BrainformWorkspace
          role="teacher"
          recordPage
          initialAgentId={q("agent_id")}
          initialSetId={q("set_id")}
          initialCourseId={q("course_id")}
          initialJobId={q("job_id")}
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
export default function TeacherRecordPage() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <TeacherRecordRoute />
    </Suspense>
  );
}
