import { AppShell } from "../../../../../../components/app-shell";
import { CreateAgentForm } from "../../../../../../components/student-workspace";
import { RouteGuard } from "../../../../../../components/session-provider";

export default async function NewAgentPage({
  params,
  searchParams,
}: {
  params: Promise<{ group_id: string }>;
  searchParams: Promise<{ return?: string }>;
}) {
  const { group_id: groupId } = await params;
  const query = await searchParams;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <CreateAgentForm groupId={groupId} returnHref={query.return} />
      </AppShell>
    </RouteGuard>
  );
}
