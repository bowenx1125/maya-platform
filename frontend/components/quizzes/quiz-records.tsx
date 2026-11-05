"use client";

import { PageBanner } from "../page-banner";
import { PageAction } from "../page-action";
import { EmptyCard } from "../ui";

export default function QuizRecords() {
  return (
    <div>
      <PageBanner title="Records">
        <PageAction name="back" href="/teacher/quizzes" placement="page" />
      </PageBanner>
      <EmptyCard>No records yet.</EmptyCard>
    </div>
  );
}
