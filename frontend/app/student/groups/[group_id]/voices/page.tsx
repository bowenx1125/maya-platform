import { AppShell } from "../../../../../components/app-shell";
import { GroupWorkspace } from "../../../../../components/student-workspace";
import { RouteGuard } from "../../../../../components/session-provider";

export default async function VoicesPage({
  params,
  searchParams,
}: {
  params: Promise<{ group_id: string }>;
  searchParams: Promise<{ mode?: string }>;
}) {
  const { group_id: groupId } = await params;
  const query = await searchParams;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <GroupWorkspace
          groupId={groupId}
          initialVoiceCreate={query.mode === "new"}
          focusVoices
        />
      </AppShell>
    </RouteGuard>
  );
}
