import { AppShell } from "../../../components/app-shell";
import { TeacherStudyformWorkspace } from "../../../components/teacher-workspace";
import { RouteGuard } from "../../../components/session-provider";

/**
 * The teacher's Teams page (sidebar Teams); ?mode=team-new /
 * team-edit&team_id open Create / Edit Team.
 */
export default async function TeacherTeamsPage({
  searchParams,
}: {
  searchParams: Promise<{ group_id?: string; mode?: string; team_id?: string }>;
}) {
  const query = await searchParams;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherStudyformWorkspace
          view="teams"
          initialGroupId={query.group_id}
          initialMode={query.mode}
          initialTeamId={query.team_id}
        />
      </AppShell>
    </RouteGuard>
  );
}
