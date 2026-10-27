import { redirect } from "next/navigation";

/**
 * Old combined teacher Studyform grid (Teams + Voices + Brainform). Split
 * pages are the real UI; keep this URL as a stub for bookmarks and old links.
 */
export default async function TeacherStudyformRedirect({
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

  if (
    query.mode === "rag-view" ||
    query.mode === "rag-edit" ||
    query.mode === "rag-new" ||
    query.mode === "knowledge-view" ||
    query.mode === "knowledge-edit"
  ) {
    const params = new URLSearchParams();
    if (query.group_id) params.set("group_id", query.group_id);
    params.set("mode", query.mode);
    if (query.document_id) params.set("document_id", query.document_id);
    const base = query.mode.startsWith("rag-")
      ? "/teacher/rag"
      : "/teacher/knowledge";
    redirect(`${base}?${params.toString()}`);
  }

  const params = new URLSearchParams();
  if (query.group_id) params.set("group_id", query.group_id);
  const next = params.toString();
  redirect(`/teacher/agents${next ? `?${next}` : ""}`);
}
