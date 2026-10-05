import { AppShell } from "../../../components/app-shell";
import { BrainformWorkspace } from "../../../components/knowledge/brainform-workspace";
import { RouteGuard } from "../../../components/session-provider";

export default async function StudentKnowledgePage({
  searchParams,
}: {
  searchParams: Promise<{
    agent_id?: string;
    set_id?: string;
    course_id?: string;
  }>;
}) {
  const query = await searchParams;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <BrainformWorkspace
          role="student"
          initialAgentId={query.agent_id}
          initialSetId={query.set_id}
          initialCourseId={query.course_id}
        />
      </AppShell>
    </RouteGuard>
  );
}
