import { AppShell } from "../../../../../components/app-shell";
import { AgentWorkbench } from "../../../../../components/agent-workspace";
import { RouteGuard } from "../../../../../components/session-provider";

export default async function AgentVersionEditPage({
  params,
}: {
  params: Promise<{ version_id: string }>;
}) {
  const { version_id: versionId } = await params;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <AgentWorkbench versionId={versionId} />
      </AppShell>
    </RouteGuard>
  );
}
