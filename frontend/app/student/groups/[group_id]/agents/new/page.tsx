import { AppShell } from "../../../../../../components/app-shell";
import { CreateAgentForm } from "../../../../../../components/student-workspace";
import { RouteGuard } from "../../../../../../components/session-provider";

export default async function NewAgentPage({
  params,
}: {
  params: Promise<{ group_id: string }>;
}) {
  const { group_id: groupId } = await params;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <CreateAgentForm groupId={groupId} />
      </AppShell>
    </RouteGuard>
  );
}
