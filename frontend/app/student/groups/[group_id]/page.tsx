import { AppShell } from "../../../../components/app-shell";
import { GroupWorkspace } from "../../../../components/student-workspace";
import { RouteGuard } from "../../../../components/session-provider";

export default async function GroupPage({
  params,
  searchParams,
}: {
  params: Promise<{ group_id: string }>;
  searchParams: Promise<{
    mode?: string;
    team_id?: string;
    document_id?: string;
  }>;
}) {
  const { group_id: groupId } = await params;
  const query = await searchParams;
  return (
    <RouteGuard role="student">
      <AppShell role="student" teamsPage={query.mode === "teams"}>
        <GroupWorkspace
          groupId={groupId}
          initialMode={query.mode}
          initialTeamId={query.team_id}
          initialDocumentId={query.document_id}
        />
      </AppShell>
    </RouteGuard>
  );
}
