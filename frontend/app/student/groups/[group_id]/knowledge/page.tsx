import { AppShell } from "../../../../../components/app-shell";
import { KnowledgeLibrary } from "../../../../../components/agent-workspace";
import { RouteGuard } from "../../../../../components/session-provider";

export default async function KnowledgePage({
  params,
}: {
  params: Promise<{ group_id: string }>;
}) {
  const { group_id: groupId } = await params;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <KnowledgeLibrary groupId={groupId} />
      </AppShell>
    </RouteGuard>
  );
}
