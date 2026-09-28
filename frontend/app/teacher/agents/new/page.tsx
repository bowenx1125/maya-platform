import { AppShell } from "../../../../components/app-shell";
import { RouteGuard } from "../../../../components/session-provider";
import { TeacherPersonalAgentCreate } from "../../../../components/teacher-workspace";

export default async function NewTeacherAgentPage({
  searchParams,
}: {
  searchParams: Promise<{ flow?: string }>;
}) {
  const query = await searchParams;
  const generationFlow = query.flow === "ai-knowledge";
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherPersonalAgentCreate generationFlow={generationFlow} />
      </AppShell>
    </RouteGuard>
  );
}
