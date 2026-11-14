import { RouteGuard } from "../../components/session-provider";
import { TeacherDashboard } from "../../components/teacher-workspace";

export default function TeacherPage() {
  return (
    <RouteGuard role="teacher">
      <TeacherDashboard />
    </RouteGuard>
  );
}
