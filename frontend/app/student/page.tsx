import { AppShell } from "../../components/app-shell";
import { RouteGuard } from "../../components/session-provider";
import { StudentDashboard } from "../../components/student-workspace";

export default function StudentPage() {
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <StudentDashboard />
      </AppShell>
    </RouteGuard>
  );
}
