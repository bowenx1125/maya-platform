import { AppShell } from "../../../components/app-shell";
import { ClassroomLive } from "../../../components/classroom-live";
import { RouteGuard } from "../../../components/session-provider";

export default function StudentLivePage() {
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <ClassroomLive />
      </AppShell>
    </RouteGuard>
  );
}
