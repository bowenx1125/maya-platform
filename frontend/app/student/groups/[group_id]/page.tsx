import { redirect } from "next/navigation";

/**
 * Old combined Studyform grid (Teams + Voices + Brainform). Split pages are
 * the real UI; keep this URL as a stub for bookmarks and old links.
 */
export default async function StudentGroupRedirect({
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
  const mode = query.mode;

  if (mode === "teams" || mode === "team-new" || mode === "team-edit") {
    const params = new URLSearchParams({ group_id: groupId });
    if (mode !== "teams") params.set("mode", mode);
    if (mode === "team-edit" && query.team_id)
      params.set("team_id", query.team_id);
    redirect(`/student/teams?${params.toString()}`);
  }

  if (
    mode === "rag-view" ||
    mode === "rag-edit" ||
    mode === "rag-new" ||
    mode === "knowledge-view" ||
    mode === "knowledge-edit"
  ) {
    const params = new URLSearchParams({ group_id: groupId, mode });
    if (query.document_id) params.set("document_id", query.document_id);
    const base = mode.startsWith("rag-")
      ? "/student/rag"
      : "/student/knowledge";
    redirect(`${base}?${params.toString()}`);
  }

  redirect(`/student/agents?group_id=${encodeURIComponent(groupId)}`);
}
