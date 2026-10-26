import { redirect } from "next/navigation";

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
  // Teams moved to /student/teams; old Studyform Team links land there.
  if (
    query.mode === "teams" ||
    query.mode === "team-new" ||
    query.mode === "team-edit"
  ) {
    const params = new URLSearchParams({ group_id: groupId });
    if (query.mode !== "teams") params.set("mode", query.mode);
    if (query.mode === "team-edit" && query.team_id)
      params.set("team_id", query.team_id);
    redirect(`/student/teams?${params.toString()}`);
  }
  return (
    <RouteGuard role="student">
      <AppShell role="student">
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
