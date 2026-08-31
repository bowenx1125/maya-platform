import { AppShell } from "../../../../../components/app-shell";
import { TeacherProviderDataCallDebatePage } from "../../../../../components/provider";
import { RouteGuard } from "../../../../../components/session-provider";

export default async function TeacherDebateProviderApprovalPage({
  params,
}: {
  params: Promise<{ debate_id: string }>;
}) {
  const { debate_id: debateId } = await params;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherProviderDataCallDebatePage debateId={debateId} />
      </AppShell>
    </RouteGuard>
  );
}
