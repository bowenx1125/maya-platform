"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { AppShell } from "../../../components/app-shell";
import { RouteGuard } from "../../../components/session-provider";
import { VoicesPage } from "../../../components/voice/voices-page";
import { LoadingPage } from "../../../components/ui";

function StudentVoicesRoute() {
  const query = useSearchParams();
  const q = (key: string) => query.get(key) ?? undefined;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <VoicesPage
          role="student"
          groupId={q("group_id")}
          initialCreate={q("mode") === "new"}
        />
      </AppShell>
    </RouteGuard>
  );
}

// The query (and path) is read in the browser, so following a link here
// needs no server render; only the page's own data requests wait.
export default function StudentVoicesPage() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <StudentVoicesRoute />
    </Suspense>
  );
}
