"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { AppShell } from "../../../components/app-shell";
import { RouteGuard } from "../../../components/session-provider";
import { VoicesPage } from "../../../components/voice/voices-page";
import { LoadingPage } from "../../../components/ui";

function TeacherVoicesRoute() {
  const query = useSearchParams();
  const q = (key: string) => query.get(key) ?? undefined;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <VoicesPage role="teacher" groupId={q("group_id")} />
      </AppShell>
    </RouteGuard>
  );
}

// The query (and path) is read in the browser, so following a link here
// needs no server render; only the page's own data requests wait.
export default function TeacherVoicesPage() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <TeacherVoicesRoute />
    </Suspense>
  );
}
