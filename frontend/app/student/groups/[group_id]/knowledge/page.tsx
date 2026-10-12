import { redirect } from "next/navigation";

export default async function StudentGroupKnowledgePage({
  params,
  searchParams,
}: {
  params: Promise<{ group_id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [{ group_id: groupId }, query] = await Promise.all([
    params,
    searchParams,
  ]);
  const next = new URLSearchParams({ group_id: groupId });
  for (const key of [
    "agent_id",
    "set_id",
    "job_id",
    "course_id",
    "mode",
    "document_id",
  ]) {
    const value = query[key];
    if (typeof value === "string") next.set(key, value);
  }
  redirect(`/student/knowledge?${next.toString()}`);
}
