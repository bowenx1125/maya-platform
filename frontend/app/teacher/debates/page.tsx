import { AppShell } from "../../../components/app-shell";
import { TeacherDebateList } from "../../../components/debate/setup/debate-setup";
import { RouteGuard } from "../../../components/session-provider";

export default function TeacherDebatesPage() {
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherDebateList />
      </AppShell>
    </RouteGuard>
  );
}
