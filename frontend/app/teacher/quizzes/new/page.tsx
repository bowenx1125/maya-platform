"use client";

import { AppShell } from "../../../../components/app-shell";
import { RouteGuard } from "../../../../components/session-provider";
import { QuizEditor } from "../../../../components/quizzes/quiz-editor";

export default function TeacherQuizNewPage() {
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <QuizEditor />
      </AppShell>
    </RouteGuard>
  );
}
