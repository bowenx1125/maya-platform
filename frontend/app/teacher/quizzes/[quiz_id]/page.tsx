"use client";

import { useParams } from "next/navigation";

import { AppShell } from "../../../../components/app-shell";
import { RouteGuard } from "../../../../components/session-provider";
import { QuizEditor } from "../../../../components/quizzes/quiz-editor";

export default function TeacherQuizEditPage() {
  const { quiz_id } = useParams<{ quiz_id: string }>();
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <QuizEditor quizId={quiz_id} />
      </AppShell>
    </RouteGuard>
  );
}
