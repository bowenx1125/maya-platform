import { AppShell } from "../../../../components/app-shell";
import { TeacherProviderDataCallPage } from "../../../../components/provider";
import { RouteGuard } from "../../../../components/session-provider";

export default async function TeacherProviderDisclosurePage({
  params,
}: {
  params: Promise<{ manifest_hash: string }>;
}) {
  const { manifest_hash: manifestHash } = await params;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherProviderDataCallPage manifestHash={manifestHash} />
      </AppShell>
    </RouteGuard>
  );
}
