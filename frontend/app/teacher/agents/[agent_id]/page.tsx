import { AppShell } from "../../../../components/app-shell";
import { RouteGuard } from "../../../../components/session-provider";
import { TeacherAgentDetail } from "../../../../components/teacher-workspace";

export default async function TeacherAgentPage({
  searchParams,
  params,
}: {
  params: Promise<{ agent_id: string }>;
  searchParams: Promise<{
    snapshot?: string;
    flow?: string;
    update_set_id?: string;
  }>;
}) {
  const [{ agent_id: agentId }, query] = await Promise.all([
    params,
    searchParams,
  ]);
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherAgentDetail
          agentId={agentId}
          snapshotId={query.snapshot}
          generationFlow={query.flow === "ai-knowledge"}
          generationSetId={query.update_set_id}
        />
      </AppShell>
    </RouteGuard>
  );
}
