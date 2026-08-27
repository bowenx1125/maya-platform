import { AppShell } from "../../../../components/app-shell";
import { TeacherDebateCreate } from "../../../../components/debate/setup/debate-setup";
import { RouteGuard } from "../../../../components/session-provider";

export default function NewTeacherDebatePage() {
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherDebateCreate />
      </AppShell>
    </RouteGuard>
  );
}
