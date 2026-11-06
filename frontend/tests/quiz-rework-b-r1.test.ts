import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  beginDoneLock,
  canStudentStartQuiz,
  releaseDoneLock,
} from "../lib/quiz-gate";
import {
  listCourseRecordAttemptsPath,
  pauseEvaluationPath,
  startEvaluationPath,
} from "../lib/quiz-urls";

describe("listCourseRecordAttemptsPath", () => {
  it("builds the teacher records path", () => {
    expect(listCourseRecordAttemptsPath("c1")).toBe(
      "courses/c1/record-attempts",
    );
  });

  it("appends quiz_id when filtering", () => {
    expect(listCourseRecordAttemptsPath("c1", "q9")).toBe(
      "courses/c1/record-attempts?quiz_id=q9",
    );
  });
});

describe("evaluation paths", () => {
  it("builds start/pause evaluation paths", () => {
    expect(startEvaluationPath("c1", "q1")).toBe(
      "courses/c1/quizzes/q1/start-evaluation",
    );
    expect(pauseEvaluationPath("c1", "q1")).toBe(
      "courses/c1/quizzes/q1/pause-evaluation",
    );
  });
});

describe("canStudentStartQuiz", () => {
  it("allows Start only when accepting_submissions is true", () => {
    expect(canStudentStartQuiz({ accepting_submissions: true })).toBe(true);
    expect(canStudentStartQuiz({ accepting_submissions: false })).toBe(false);
    expect(canStudentStartQuiz({})).toBe(false);
    expect(canStudentStartQuiz({ accepting_submissions: null })).toBe(false);
  });
});

describe("Done in-flight lock", () => {
  it("rejects a second begin while held", () => {
    const lock = { current: false };
    expect(beginDoneLock(lock)).toBe(true);
    expect(beginDoneLock(lock)).toBe(false);
    releaseDoneLock(lock);
    expect(beginDoneLock(lock)).toBe(true);
  });
});

describe("EmptyCard title usage (W1 smoke)", () => {
  it("quizzes-list empty state uses EmptyCard title prop", () => {
    const src = readFileSync(
      join(__dirname, "../components/quizzes/quizzes-list.tsx"),
      "utf8",
    );
    expect(src).toContain('title={t("noQuizzes")}');
    expect(src).not.toMatch(/<EmptyCard>\{\s*t\("noQuizzes"\)\s*\}<\/EmptyCard>/);
  });
});

describe("quiz-editor Done debounce + no bottom Save", () => {
  it("uses beginDoneLock and drops bottom Save CTA", () => {
    const src = readFileSync(
      join(__dirname, "../components/quizzes/quiz-editor.tsx"),
      "utf8",
    );
    expect(src).toContain("beginDoneLock");
    expect(src).not.toMatch(/onClick=\{onSave\}/);
    expect(src).not.toMatch(/>\s*Save\s*</);
  });
});
