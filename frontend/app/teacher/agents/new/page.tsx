"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { RouteGuard } from "../../../../components/session-provider";
import { TeacherPersonalAgentCreate } from "../../../../components/teacher-workspace";
import { LoadingPage } from "../../../../components/ui";

function NewTeacherAgentRoute() {
  const query = useSearchParams();
  const q = (key: string) => query.get(key) ?? undefined;
  return (
    <RouteGuard role="teacher">
      <TeacherPersonalAgentCreate returnHref={q("return")} />
    </RouteGuard>
  );
}

// The query (and path) is read in the browser, so following a link here
// needs no server render; only the page's own data requests wait.
export default function NewTeacherAgentPage() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <NewTeacherAgentRoute />
    </Suspense>
  );
}
