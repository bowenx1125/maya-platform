import { AppShell } from "../../../components/app-shell";
import { QuizzesList } from "../../../components/quizzes/quizzes-list";
import { RouteGuard } from "../../../components/session-provider";

export default function TeacherQuizzesPage() {
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <QuizzesList />
      </AppShell>
    </RouteGuard>
  );
}
