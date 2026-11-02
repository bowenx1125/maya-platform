"use client";

import { useParams } from "next/navigation";

import { AppShell } from "../../../../../components/app-shell";
import { AgentWorkbench } from "../../../../../components/agent-workspace";
import { RouteGuard } from "../../../../../components/session-provider";

// The query (and path) is read in the browser, so following a link here
// needs no server render; only the page's own data requests wait.
export default function AgentVersionEditPage() {
  const { version_id: versionId } = useParams<{ version_id: string }>();
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <AgentWorkbench versionId={versionId} publishOnDone />
      </AppShell>
    </RouteGuard>
  );
}
