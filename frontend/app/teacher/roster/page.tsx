import { AppShell } from "../../../components/app-shell";
import { RosterWorkspace } from "../../../components/roster-workspace";
import { RouteGuard } from "../../../components/session-provider";

export default function TeacherRosterPage() {
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <RosterWorkspace />
      </AppShell>
    </RouteGuard>
  );
}
