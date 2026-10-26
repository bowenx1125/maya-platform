import { AppShell } from "../../../components/app-shell";
import { TeacherStudyformWorkspace } from "../../../components/teacher-workspace";
import { RouteGuard } from "../../../components/session-provider";

/** The teacher's Agents page (sidebar Agents). */
export default async function TeacherAgentsPage({
  searchParams,
}: {
  searchParams: Promise<{ group_id?: string }>;
}) {
  const query = await searchParams;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherStudyformWorkspace
          view="agents"
          initialGroupId={query.group_id}
        />
      </AppShell>
    </RouteGuard>
  );
}
