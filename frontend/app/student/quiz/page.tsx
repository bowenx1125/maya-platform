import { AppShell } from "../../../components/app-shell";
import { QuizPage } from "../../../components/quiz/quiz-page";
import { RouteGuard } from "../../../components/session-provider";

/** One Quiz list; an old ?tab=records link lands on the same list. */
export default function StudentQuizPage() {
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <QuizPage />
      </AppShell>
    </RouteGuard>
  );
}
