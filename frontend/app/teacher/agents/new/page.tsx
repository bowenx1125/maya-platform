import { AppShell } from "../../../../components/app-shell";
import { RouteGuard } from "../../../../components/session-provider";
import { TeacherPersonalAgentCreate } from "../../../../components/teacher-workspace";

export default async function NewTeacherAgentPage({
  searchParams,
}: {
  searchParams: Promise<{ return?: string }>;
}) {
  const query = await searchParams;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherPersonalAgentCreate returnHref={query.return} />
      </AppShell>
    </RouteGuard>
  );
}
