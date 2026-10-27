import { redirect } from "next/navigation";

/** Old combined Studyform Voices pane → dedicated Voices page. */
export default async function StudentGroupVoicesRedirect({
  params,
  searchParams,
}: {
  params: Promise<{ group_id: string }>;
  searchParams: Promise<{ mode?: string }>;
}) {
  const { group_id: groupId } = await params;
  const query = await searchParams;
  const next = new URLSearchParams({ group_id: groupId });
  if (query.mode === "new") next.set("mode", "new");
  redirect(`/student/voices?${next.toString()}`);
}
