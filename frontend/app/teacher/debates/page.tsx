import { TeacherDebateList } from "../../../components/debate/setup/debate-setup";
import { RouteGuard } from "../../../components/session-provider";

export default function TeacherDebatesPage() {
  return (
    <RouteGuard role="teacher">
      <TeacherDebateList />
    </RouteGuard>
  );
}
