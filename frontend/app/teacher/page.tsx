import { AppShell } from "../../components/app-shell";
import { RouteGuard } from "../../components/session-provider";
import { TeacherDashboard } from "../../components/teacher-workspace";

export default function TeacherPage() {
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <TeacherDashboard />
      </AppShell>
    </RouteGuard>
  );
}
