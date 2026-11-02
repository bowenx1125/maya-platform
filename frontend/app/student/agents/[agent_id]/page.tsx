"use client";

import { useParams } from "next/navigation";

import { AppShell } from "../../../../components/app-shell";
import { AgentOverview } from "../../../../components/agent-workspace";
import { RouteGuard } from "../../../../components/session-provider";

// The query (and path) is read in the browser, so following a link here
// needs no server render; only the page's own data requests wait.
export default function AgentPage() {
  const { agent_id: agentId } = useParams<{ agent_id: string }>();
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <AgentOverview agentId={agentId} />
      </AppShell>
    </RouteGuard>
  );
}
