"use client";

import { AppShell } from "../../../../components/app-shell";
import { RouteGuard } from "../../../../components/session-provider";
import QuizRecords from "../../../../components/quizzes/quiz-records";

export default function TeacherQuizRecordsPage() {
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <QuizRecords />
      </AppShell>
    </RouteGuard>
  );
}
