import { AppShell } from "../../../../components/app-shell";
import { GroupWorkspace } from "../../../../components/student-workspace";
import { RouteGuard } from "../../../../components/session-provider";

export default async function GroupPage({
  params,
}: {
  params: Promise<{ group_id: string }>;
}) {
  const { group_id: groupId } = await params;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <GroupWorkspace groupId={groupId} />
      </AppShell>
    </RouteGuard>
  );
}
