import { redirect } from "next/navigation";

import { QUIZ_RECORDS_PATH } from "../../../lib/quiz-draft";

// Owner decision (2026-11-08): Record moved from Brainform into the Quiz
// page's Records tab; the old address keeps working for bookmarks and links.
export default function StudentRecordPage() {
  redirect(QUIZ_RECORDS_PATH);
}
