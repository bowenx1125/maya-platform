import { AppShell } from "../../../components/app-shell";
import { RouteGuard } from "../../../components/session-provider";
import { VoicesPage } from "../../../components/voice/voices-page";

export default async function TeacherVoicesPage({
  searchParams,
}: {
  searchParams: Promise<{ group_id?: string }>;
}) {
  const query = await searchParams;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <VoicesPage role="teacher" groupId={query.group_id} />
      </AppShell>
    </RouteGuard>
  );
}
