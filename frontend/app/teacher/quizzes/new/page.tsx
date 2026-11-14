"use client";

import { RouteGuard } from "../../../../components/session-provider";
import { QuizEditor } from "../../../../components/quizzes/quiz-editor";

export default function TeacherQuizNewPage() {
  return (
    <RouteGuard role="teacher">
      <QuizEditor />
    </RouteGuard>
  );
}
