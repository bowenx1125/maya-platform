import { redirect } from "next/navigation";

import { QUIZ_RECORDS_PATH } from "../../../lib/quiz-draft";

/**
 * The old Brainform Record page for students moved under Quiz (M4). A tiny
 * server redirect; the Quiz page owns the Records tab now. A query that
 * names a course (course_id) survives so Quiz Records reads the same course.
 */
export default async function StudentRecordPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "string") query.set(key, value);
  }
  const qs = query.toString();
  redirect(qs ? `${QUIZ_RECORDS_PATH}&${qs}` : QUIZ_RECORDS_PATH);
}
