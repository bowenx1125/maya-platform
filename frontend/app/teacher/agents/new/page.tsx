import { AppShell } from "../../../../components/app-shell";
import { RouteGuard } from "../../../../components/session-provider";
import { TeacherPersonalAgentCreate } from "../../../../components/teacher-workspace";

export default function NewTeacherAgentPage() {
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherPersonalAgentCreate />
      </AppShell>
    </RouteGuard>
  );
}
