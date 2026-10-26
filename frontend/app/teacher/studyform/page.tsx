import { redirect } from "next/navigation";

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
    document_id?: string;
  }>;
}) {
  const query = await searchParams;
  // Teams moved to /teacher/teams; old Studyform Team links land there.
  const teamMode =
    query.mode === "maya-new"
      ? "team-new"
      : query.mode === "maya-edit"
        ? "team-edit"
        : query.mode;
  if (
    teamMode === "teams" ||
    teamMode === "team-new" ||
    teamMode === "team-edit"
  ) {
    const params = new URLSearchParams();
    if (query.group_id) params.set("group_id", query.group_id);
    if (teamMode !== "teams") params.set("mode", teamMode);
    if (teamMode === "team-edit" && query.team_id)
      params.set("team_id", query.team_id);
    const next = params.toString();
    redirect(`/teacher/teams${next ? `?${next}` : ""}`);
  }
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherStudyformWorkspace
          initialGroupId={query.group_id}
          initialMode={query.mode}
          initialTeamId={query.team_id}
          initialDocumentId={query.document_id}
        />
      </AppShell>
    </RouteGuard>
  );
}
