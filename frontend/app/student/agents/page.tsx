import { AppShell } from "../../../components/app-shell";
import { StudentAgentsPage } from "../../../components/student-workspace";
import { RouteGuard } from "../../../components/session-provider";

/** A group's Agents page (sidebar Agents); ?group_id picks the group. */
export default async function AgentsPage({
  searchParams,
}: {
  searchParams: Promise<{ group_id?: string }>;
}) {
  const query = await searchParams;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <StudentAgentsPage groupId={query.group_id} />
      </AppShell>
    </RouteGuard>
  );
}
