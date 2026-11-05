"use client";

import { useEffect, useState } from "react";

import type { QuizSummary } from "../../lib/api";
import { useSession } from "../session-provider";
import { LoadingCard } from "../ui";
import { PageBanner } from "../page-banner";
import { QuizAvailable } from "./quiz-available";
import { QuizRecords } from "./quiz-records";
import { QuizTake } from "./quiz-take";

export type QuizTab = "available" | "records";

/**
 * The two-tab student Quiz page; no secondary description under the title.
 * Tab switching is local state; ?tab=records lands on Records once.
 */
export function QuizPage({ initialTab }: { initialTab?: QuizTab }) {
  const { user } = useSession();
  // Same course resolution as ClassroomLive.
  const courseId = user?.courses[0]?.course_id;
  const [tab, setTab] = useState<QuizTab>(initialTab ?? "available");
  const [taking, setTaking] = useState<QuizSummary | null>(null);

  return (
    <div className="mx-auto w-full max-w-[1120px]">
      <PageBanner title="Quiz" titleId="quiz-page-title" />
      <div role="tablist" aria-label="Quiz" className="mb-5 flex gap-2.5">
        {(
          [
            ["available", "Available"],
            ["records", "Records"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => {
              setTab(key);
              setTaking(null);
            }}
            className={`inline-flex min-h-10 cursor-pointer items-center rounded-arc-s border-[3px] border-border px-4 py-2 font-body text-sm font-bold text-ink shadow-[0_4px_0_#111] transition-[translate,box-shadow] duration-[80ms] active:translate-y-1 active:shadow-none motion-reduce:transition-none ${
              tab === key ? "bg-main text-main-fg" : "bg-surface"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {courseId === undefined ? (
        <LoadingCard />
      ) : taking ? (
        <QuizTake
          courseId={courseId}
          quizId={taking.id}
          onExit={() => {
            setTaking(null);
            setTab("available");
          }}
        />
      ) : tab === "records" ? (
        <QuizRecords courseId={courseId} />
      ) : (
        <QuizAvailable
          courseId={courseId}
          onStart={(quiz) => setTaking(quiz)}
        />
      )}
    </div>
  );
}
