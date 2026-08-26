import { AppShell } from "../../../../components/app-shell";
import { StudentPublishedVersion } from "../../../../components/agent-workspace";
import { RouteGuard } from "../../../../components/session-provider";

export default async function StudentPublishedVersionPage({
  params,
}: {
  params: Promise<{ version_id: string }>;
}) {
  const { version_id: versionId } = await params;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <StudentPublishedVersion versionId={versionId} />
      </AppShell>
    </RouteGuard>
  );
}
