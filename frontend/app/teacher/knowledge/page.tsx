import { AppShell } from "../../../components/app-shell";
import { KnowledgeSetWorkspace } from "../../../components/knowledge/knowledge-set-workspace";
import { RouteGuard } from "../../../components/session-provider";

export default async function TeacherKnowledgePage({
  searchParams,
}: {
  searchParams: Promise<{ agent_id?: string }>;
}) {
  const query = await searchParams;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <KnowledgeSetWorkspace agentId={query.agent_id} />
      </AppShell>
    </RouteGuard>
  );
}
