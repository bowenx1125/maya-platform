import { AppShell } from "../../../components/app-shell";
import { BrainformWorkspace } from "../../../components/knowledge/brainform-workspace";
import { RouteGuard } from "../../../components/session-provider";

export default async function TeacherRagPage({
  searchParams,
}: {
  searchParams: Promise<{
    agent_id?: string;
    set_id?: string;
    job_id?: string;
    course_id?: string;
    group_id?: string;
    mode?: string;
    document_id?: string;
  }>;
}) {
  const query = await searchParams;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <BrainformWorkspace
          role="teacher"
          ragPage
          initialAgentId={query.agent_id}
          initialSetId={query.set_id}
          initialCourseId={query.course_id}
          initialJobId={query.job_id}
          initialGroupId={query.group_id}
          initialMode={query.mode}
          initialDocumentId={query.document_id}
        />
      </AppShell>
    </RouteGuard>
  );
}
