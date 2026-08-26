import { AppShell } from "../../../../../components/app-shell";
import { VoiceLibrary } from "../../../../../components/voice/voice-library";
import { RouteGuard } from "../../../../../components/session-provider";

export default async function VoicesPage({
  params,
}: {
  params: Promise<{ group_id: string }>;
}) {
  const { group_id: groupId } = await params;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <VoiceLibrary groupId={groupId} />
      </AppShell>
    </RouteGuard>
  );
}
