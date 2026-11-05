import { describe, expect, it } from "vitest";

import {
  classroomGroupKeys,
  litSidebarKey,
} from "../components/app-shell";
import {
  clearQuizDraft,
  QUIZ_RECORDS_PATH,
  quizDraftKey,
  readQuizDraft,
  writeQuizDraft,
} from "../lib/quiz-draft";
import {
  sanitizeStudentQuiz,
} from "../lib/api/platform";
import {
  listCourseQuizzesPath,
  getStudentQuizPath,
  submitQuizAttemptPath,
  listMyRecordAttemptsPath,
} from "../lib/quiz-urls";
import type { StudentQuizDto } from "../lib/api/platform";

// M4 acceptance: IA Quiz, no Brainform Record row for students, one
// localStorage key per course/user/quiz, Quiz Records path, and a
// zero-LLM request path.

describe("quiz draft key", () => {
  it("formats the key exactly: quiz-draft:{courseId}:{userId}:{quizId}", () => {
    expect(quizDraftKey("course-1", "user-2", "quiz-3")).toBe(
      "quiz-draft:course-1:user-2:quiz-3",
    );
  });

  it("round-trips a draft and clears it; absent storage stays quiet", () => {
    writeQuizDraft("c", "u", "q", { item1: { choice_ids: ["a"] } });
    expect(readQuizDraft("c", "u", "q")).toEqual({
      item1: { choice_ids: ["a"] },
    });
    clearQuizDraft("c", "u", "q");
    expect(readQuizDraft("c", "u", "q")).toBeNull();
    // A quiz with no draft reads as null, never throws.
    expect(readQuizDraft("c", "u", "other")).toBeNull();
  });
});

describe("sanitizeStudentQuiz", () => {
  const leaked = {
    id: "quiz-1",
    course_id: "course-1",
    group_id: null,
    title: "Chapter 1 Quiz",
    status: "published",
    schema_version: 1,
    content_revision: 2,
    settings: {
      shuffle_questions: false,
      shuffle_choices: false,
      allow_skip: false,
      time_limit_sec: null,
    },
    locale: "en",
    published_at: "2026-11-05T00:00:00Z",
    items: [
      {
        id: "q1",
        type: "single",
        required: true,
        prompt: "Pick one",
        choices: [
          { id: "a", label: "Alpha" },
          { id: "b", label: "Beta" },
        ],
        points: 1,
        // Teacher-projection keys a buggy server must not pass through:
        answer: { choice_ids: ["a"], rubric: "because" },
        rubric: "secret",
      },
      {
        id: "q2",
        type: "long_text",
        required: true,
        prompt: "Explain",
        choices: [],
        points: 2,
        answer: { rubric: "graded by hand" },
      },
    ],
  } as unknown as StudentQuizDto;

  it("strips answer/rubric from every item (defense in depth)", () => {
    const safe = sanitizeStudentQuiz(leaked);
    for (const item of safe.items) {
      expect(item).not.toHaveProperty("answer");
      expect(item).not.toHaveProperty("rubric");
    }
    expect(safe.items[0]?.choices).toEqual([
      { id: "a", label: "Alpha" },
      { id: "b", label: "Beta" },
    ]);
    expect(safe.title).toBe("Chapter 1 Quiz");
  });
});

describe("quiz request paths (zero LLM)", () => {
  it("hits only the four frozen student ops", () => {
    expect(listCourseQuizzesPath("c1")).toBe("courses/c1/quizzes");
    expect(getStudentQuizPath("c1", "q1")).toBe("courses/c1/quizzes/q1");
    expect(submitQuizAttemptPath("c1", "q1")).toBe(
      "courses/c1/quizzes/q1/attempts",
    );
    expect(listMyRecordAttemptsPath("c1")).toBe("courses/c1/my-record-attempts");
  });
});

describe("sidebar Quiz IA", () => {
  it("the Classroom group includes quiz for students and teachers", () => {
    const student = classroomGroupKeys(false);
    const teacher = classroomGroupKeys(true);
    expect(student).toContain("quiz");
    expect(teacher).toContain("quiz");
  });

  it("student and teacher Brainform rows keep Record (Quiz Records is separate)", () => {
    expect(studentBrainformKeys()).toContain("record");
    expect(teacherBrainformKeys()).toContain("record");
  });

  it("/student/quiz lights the classroom:quiz row; /student/record lights record (teacher keeps it)", () => {
    const groups = [
      {
        key: "classroom",
        items: [
          { key: "quiz", href: "/student/quiz" },
        ],
      },
    ];
    expect(litSidebarKey(groups, "/student/quiz", "/student/quiz")).toBe(
      "classroom:quiz",
    );
    const teacherGroups = [
      {
        key: "brainform",
        items: [{ key: "record", href: "/teacher/record" }],
      },
    ];
    expect(litSidebarKey(teacherGroups, "/teacher/record", "/teacher/record")).toBe(
      "brainform:record",
    );
  });
});

describe("quiz records path", () => {
  it("Quiz Records tab path stays available alongside Brainform Record", () => {
    expect(QUIZ_RECORDS_PATH).toBe("/student/quiz?tab=records");
  });
});

/** Mirrors app-shell's student Brainform row list (Record kept alongside Quiz). */
function studentBrainformKeys(): string[] {
  return ["rag", "voices", "record"];
}

function teacherBrainformKeys(): string[] {
  return ["rag", "voices", "record"];
}

describe("Available row hit layer", () => {
  it("does not put PRESS_MOTION/PRESS_HIT on the row (Start must stay clickable)", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const src = readFileSync(
      join(__dirname, "../components/quiz/quiz-available.tsx"),
      "utf8",
    );
    expect(src).not.toMatch(/PRESS_MOTION/);
    expect(src).not.toMatch(/hover:after:absolute/);
    expect(src).toContain("Start");
  });
});
