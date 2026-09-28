import { AppShell } from "../../../components/app-shell";
import { KnowledgeSetWorkspace } from "../../../components/knowledge/knowledge-set-workspace";
import { RouteGuard } from "../../../components/session-provider";

export default async function StudentKnowledgePage({
  searchParams,
}: {
  searchParams: Promise<{ agent_id?: string }>;
}) {
  const query = await searchParams;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <KnowledgeSetWorkspace agentId={query.agent_id} role="student" />
      </AppShell>
    </RouteGuard>
  );
}
