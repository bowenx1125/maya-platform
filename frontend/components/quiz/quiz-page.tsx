"use client";

import { useState } from "react";

import type { QuizSummary } from "../../lib/api";
import { useSession } from "../session-provider";
import { LoadingCard } from "../ui";
import { PageBanner } from "../page-banner";
import { StudentQuizList } from "./quiz-list";
import { QuizTake } from "./quiz-take";

/**
 * The student Quiz page (option A, 2026-11-08): one list, no tabs. Quizzes
 * to take, own results and not-yet-open quizzes share it; Start opens the
 * take view in place.
 */
export function QuizPage() {
  const { user } = useSession();
  // Same course resolution as ClassroomLive.
  const courseId = user?.courses[0]?.course_id;
  const [taking, setTaking] = useState<QuizSummary | null>(null);
  const [returned, setReturned] = useState(false);

  return (
    <div className="mx-auto w-full max-w-[1120px]">
      <PageBanner title="Quiz" titleId="quiz-page-title" />
      {courseId === undefined ? (
        <LoadingCard />
      ) : taking ? (
        <QuizTake
          courseId={courseId}
          quizId={taking.id}
          onExit={() => {
            setTaking(null);
            setReturned(true);
          }}
        />
      ) : (
        <StudentQuizList
          courseId={courseId}
          fresh={returned}
          onStart={(quiz) => setTaking(quiz)}
        />
      )}
    </div>
  );
}
