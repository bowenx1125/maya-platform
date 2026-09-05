import { AppShell } from "../../../components/app-shell";
import { BetaDebateList } from "../../../components/debate-beta/beta-debate-list";
import { RouteGuard } from "../../../components/session-provider";

export default function TeacherDebatesBetaPage() {
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <BetaDebateList />
      </AppShell>
    </RouteGuard>
  );
}
