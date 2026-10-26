import { AppShell } from "../../../components/app-shell";
import { StudentTeamsPage } from "../../../components/student-workspace";
import { RouteGuard } from "../../../components/session-provider";

/**
 * A group's Teams page (sidebar Teams); ?group_id picks the group and
 * ?mode=team-new / team-edit&team_id open Create / Edit Team.
 */
export default async function TeamsRoute({
  searchParams,
}: {
  searchParams: Promise<{ group_id?: string; mode?: string; team_id?: string }>;
}) {
  const query = await searchParams;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <StudentTeamsPage
          groupId={query.group_id}
          mode={query.mode}
          teamId={query.team_id}
        />
      </AppShell>
    </RouteGuard>
  );
}
