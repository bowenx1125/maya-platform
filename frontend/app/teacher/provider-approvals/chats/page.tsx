import { AppShell } from "../../../../components/app-shell";
import { TeacherChatProviderApprovalsPage } from "../../../../components/provider";
import { RouteGuard } from "../../../../components/session-provider";

export default async function TeacherChatProviderApprovalsRoute({
  searchParams,
}: {
  searchParams: Promise<{ course_id?: string }>;
}) {
  const { course_id: courseId = "" } = await searchParams;
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherChatProviderApprovalsPage courseId={courseId} />
      </AppShell>
    </RouteGuard>
  );
}
