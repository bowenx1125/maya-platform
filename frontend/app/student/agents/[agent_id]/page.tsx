import { AppShell } from "../../../../components/app-shell";
import { AgentOverview } from "../../../../components/agent-workspace";
import { RouteGuard } from "../../../../components/session-provider";

export default async function AgentPage({
  params,
}: {
  params: Promise<{ agent_id: string }>;
}) {
  const { agent_id: agentId } = await params;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <AgentOverview agentId={agentId} />
      </AppShell>
    </RouteGuard>
  );
}
