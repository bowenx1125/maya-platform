import { AppShell } from "../../../components/app-shell";
import { RouteGuard } from "../../../components/session-provider";
import { VoicesPage } from "../../../components/voice/voices-page";

export default async function StudentVoicesPage({
  searchParams,
}: {
  searchParams: Promise<{ group_id?: string; mode?: string }>;
}) {
  const query = await searchParams;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <VoicesPage
          role="student"
          groupId={query.group_id}
          initialCreate={query.mode === "new"}
        />
      </AppShell>
    </RouteGuard>
  );
}
