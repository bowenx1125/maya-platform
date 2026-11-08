import { redirect } from "next/navigation";

/**
 * Records moved into each quiz (option A, 2026-11-08): a quiz's submissions
 * are the Submissions tab of its page. Old links keep working.
 */
export default async function TeacherQuizRecordsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const quizId = typeof params.quiz_id === "string" ? params.quiz_id : "";
  redirect(
    quizId.trim()
      ? `/teacher/quizzes/${encodeURIComponent(quizId)}?tab=submissions`
      : "/teacher/quizzes",
  );
}
