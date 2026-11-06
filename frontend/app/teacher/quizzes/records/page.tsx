"use client";

import { Suspense } from "react";

import { AppShell } from "../../../../components/app-shell";
import { RouteGuard } from "../../../../components/session-provider";
import QuizRecords from "../../../../components/quizzes/quiz-records";
import { LoadingPage } from "../../../../components/ui";

function TeacherQuizRecordsRoute() {
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <QuizRecords />
      </AppShell>
    </RouteGuard>
  );
}

export default function TeacherQuizRecordsPage() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <TeacherQuizRecordsRoute />
    </Suspense>
  );
}
