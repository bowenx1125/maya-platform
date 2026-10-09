import { AppShell } from "../../../components/app-shell";
import { TeacherStudyformWorkspace } from "../../../components/teacher-workspace";
import { RouteGuard } from "../../../components/session-provider";

export default async function TeacherStudyformPage({
  searchParams,
}: {
  searchParams: Promise<{
    group_id?: string;
    mode?: string;
    team_id?: string;
  }>;
}) {
  const query = await searchParams;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherStudyformWorkspace
          initialGroupId={query.group_id}
          initialMode={query.mode}
          initialTeamId={query.team_id}
        />
      </AppShell>
    </RouteGuard>
  );
}
