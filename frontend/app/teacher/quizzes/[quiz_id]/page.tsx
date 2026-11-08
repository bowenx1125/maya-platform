"use client";

import { Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";

import { AppShell } from "../../../../components/app-shell";
import { RouteGuard } from "../../../../components/session-provider";
import { QuizEditor } from "../../../../components/quizzes/quiz-editor";
import { LoadingPage } from "../../../../components/ui";

function TeacherQuizRoute() {
  const { quiz_id } = useParams<{ quiz_id: string }>();
  const tab = useSearchParams().get("tab");
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <QuizEditor
          key={quiz_id}
          quizId={quiz_id}
          initialTab={
            tab === "submissions" || tab === "paper" ? tab : undefined
          }
        />
      </AppShell>
    </RouteGuard>
  );
}

/** One page per quiz: ?tab=paper|submissions picks the opening tab. */
export default function TeacherQuizPage() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <TeacherQuizRoute />
    </Suspense>
  );
}
