import { KnowledgeLibrary } from "../../../../../components/knowledge";
import { AppShell } from "../../../../../components/app-shell";
import { RouteGuard } from "../../../../../components/session-provider";

export default async function TeacherGroupKnowledgePage({
  params,
}: {
  params: Promise<{ group_id: string }>;
}) {
  const { group_id: groupId } = await params;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <KnowledgeLibrary groupId={groupId} teacherReadOnly />
      </AppShell>
    </RouteGuard>
  );
}
