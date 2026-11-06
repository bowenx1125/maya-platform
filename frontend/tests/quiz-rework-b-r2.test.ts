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
  pauseTakingPath,
  startTakingPath,
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

describe("taking paths", () => {
  it("builds start/pause taking paths", () => {
    expect(startTakingPath("c1", "q1")).toBe(
      "courses/c1/quizzes/q1/start-taking",
    );
    expect(pauseTakingPath("c1", "q1")).toBe(
      "courses/c1/quizzes/q1/pause-taking",
    );
  });
});

describe("canStudentStartQuiz", () => {
  it("allows Start only when taking_open is true", () => {
    expect(canStudentStartQuiz({ taking_open: true })).toBe(true);
    expect(canStudentStartQuiz({ taking_open: false })).toBe(false);
    expect(canStudentStartQuiz({})).toBe(false);
    expect(canStudentStartQuiz({ taking_open: null })).toBe(false);
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
    expect(src).not.toMatch(
      /<EmptyCard>\{\s*t\("noQuizzes"\)\s*\}<\/EmptyCard>/,
    );
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

describe("formal taking contract wiring", () => {
  it("FE source has no provisional accepting_submissions / *-evaluation paths", () => {
    const files = [
      "../lib/quiz-gate.ts",
      "../lib/quiz-urls.ts",
      "../lib/api/quiz.ts",
      "../lib/api/platform.ts",
      "../components/quizzes/quizzes-list.tsx",
      "../components/quizzes/quiz-editor.tsx",
      "../components/quiz/quiz-available.tsx",
    ];
    for (const rel of files) {
      const src = readFileSync(join(__dirname, rel), "utf8");
      expect(src, rel).not.toMatch(/accepting_submissions/);
      expect(src, rel).not.toMatch(/start-evaluation|pause-evaluation/);
      expect(src, rel).not.toMatch(/startEvaluation|pauseEvaluation/);
    }
  });
});
