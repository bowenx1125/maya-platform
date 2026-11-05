import { AppShell } from "../../../components/app-shell";
import { QuizPage, type QuizTab } from "../../../components/quiz/quiz-page";
import { RouteGuard } from "../../../components/session-provider";

/** Records lands as a tab on Quiz (M4); ?tab=records deep-links there. */
export default async function StudentQuizPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const tab = params.tab === "records" ? "records" : undefined;
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <QuizPage initialTab={tab as QuizTab | undefined} />
      </AppShell>
    </RouteGuard>
  );
}
