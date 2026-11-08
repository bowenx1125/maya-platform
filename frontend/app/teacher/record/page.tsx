import { redirect } from "next/navigation";

// Owner decision (2026-11-08): Record moved from Brainform into Quizzes
// (now each quiz's Submissions tab); the old address keeps working for bookmarks and links.
export default function TeacherRecordPage() {
  redirect("/teacher/quizzes");
}
