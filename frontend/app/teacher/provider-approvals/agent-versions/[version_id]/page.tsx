import { AppShell } from "../../../../../components/app-shell";
import { TeacherProviderDataCallPublicationPage } from "../../../../../components/provider";
import { RouteGuard } from "../../../../../components/session-provider";

export default async function TeacherProviderPublicationApprovalPage({
  params,
}: {
  params: Promise<{ version_id: string }>;
}) {
  const { version_id: agentVersionId } = await params;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherProviderDataCallPublicationPage
          agentVersionId={agentVersionId}
        />
      </AppShell>
    </RouteGuard>
  );
}
