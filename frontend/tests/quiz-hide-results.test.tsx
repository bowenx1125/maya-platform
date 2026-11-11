import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformApi } from "../lib/api/platform";
import { invalidateRequestCache } from "../lib/request-cache";

const state = vi.hoisted(() => ({
  push: vi.fn(),
  api: {} as Record<string, unknown>,
  role: "teacher" as "teacher" | "student",
  routes: [] as Array<{
    match: RegExp;
    body: unknown;
    status?: number;
    method?: string;
  }>,
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    identityGeneration: 1,
    user: {
      id: state.role === "teacher" ? "teacher-1" : "user-1",
      courses: [{ course_id: "course-1", role: state.role }],
      groups: [],
    },
  }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.push }),
  usePathname: () => "/teacher/quizzes/quiz-1",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("../lib/confetti", () => ({ celebrate: vi.fn() }));

import QuizEditor from "../components/quizzes/quiz-editor";
import { QuizSubmissions } from "../components/quizzes/quiz-submissions";
import { StudentQuizList } from "../components/quiz/quiz-list";
import { QuizAttemptDetailView } from "../components/quiz/quiz-attempt-detail";
import { QuizTake } from "../components/quiz/quiz-take";

const base = {
  course_id: "course-1",
  schema_version: 1,
  content_revision: 1,
  created_by_user_id: "teacher-1",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-08T00:00:00Z",
};

const publishedQuiz = {
  ...base,
  id: "q-live",
  title: "Week 9",
  status: "published",
  taking_open: true,
  settings: {},
  items: [
    {
      id: "q1",
      type: "single",
      prompt: "Which layer handles auth?",
      choices: [
        { id: "a", label: "API gateway" },
        { id: "b", label: "Database" },
      ],
      answer: { choice_ids: ["a"] },
      points: 2,
    },
  ],
};

const studentQuiz = {
  id: "quiz-1",
  course_id: "course-1",
  group_id: null,
  title: "Week 3 Quiz",
  status: "published" as const,
  schema_version: 1,
  content_revision: 1,
  settings: {
    shuffle_questions: false,
    shuffle_choices: false,
    allow_skip: true,
    time_limit_sec: null,
  },
  locale: "en",
  items: [
    {
      id: "q1",
      type: "single" as const,
      required: true,
      prompt: "Which layer handles auth?",
      choices: [
        { id: "a", label: "API gateway" },
        { id: "b", label: "Database" },
      ],
      points: 3,
    },
    {
      id: "q3",
      type: "short_text" as const,
      required: true,
      prompt: "Name one reason to use a queue.",
      choices: [],
      points: 3,
    },
  ],
  taking_open: true,
  taking_epoch: 2,
  published_at: "2026-11-08T00:00:00Z",
};

const quizRow = {
  source: "quiz",
  attempt_id: "att-1",
  user_id: "student-1",
  student_name: "Ada",
  title: "Week 3 Quiz",
  status: "submitted",
  submitted_at: "2026-11-08T01:00:00Z",
  score_objective: 3,
  score_max_objective: 3,
  grading_status: "mixed",
  quiz_id: "quiz-1",
  conversation_id: null,
  points_awarded: 3,
  points_total: 6,
  phase: "grading_pending",
  team_name: null,
  taking_epoch: 2,
  content_revision: 1,
};

function attemptDetail(
  view: "teacher" | "student",
  resultsVisible?: boolean,
) {
  const visible = resultsVisible === true;
  return {
    view,
    id: "att-1",
    quiz_id: "quiz-1",
    course_id: "course-1",
    user_id: "student-1",
    student_name: "Ada",
    title: "Week 3 Quiz",
    content_revision: 1,
    taking_epoch: 2,
    status: "submitted",
    ...(resultsVisible === undefined ? {} : { results_visible: resultsVisible }),
    ...(visible || view === "teacher"
      ? {
          grading_status: "mixed",
          score_objective: 3,
          score_max_objective: 3,
          score_manual: 0,
          score_max_manual: 3,
          score_ai: 2,
          points_awarded: 3,
          points_total: 6,
        }
      : {}),
    submitted_at: "2026-11-08T01:00:00Z",
    graded_at: null,
    items: [
      {
        id: "q1",
        type: "single",
        prompt: "Which layer handles auth?",
        choices: [
          { id: "a", label: "API gateway" },
          { id: "b", label: "Database" },
        ],
        points: 3,
        response_choice_ids: ["a"],
        ...(visible || view === "teacher"
          ? { correct: true, points_awarded: 3, graded: true }
          : {}),
        ...(view === "teacher" ? { answer: { choice_ids: ["a"] } } : {}),
      },
      {
        id: "q3",
        type: "short_text",
        prompt: "Name one reason to use a queue.",
        choices: [],
        points: 3,
        response_text: "Decouple producers",
        graded: true,
        ...(visible || view === "teacher"
          ? {
              points_awarded: 2,
              feedback: "Name a second reason.",
              ai_score: 2,
            }
          : {}),
        ...(view === "teacher"
          ? { answer: { rubric: "Mentions decoupling." } }
          : {}),
      },
    ],
  };
}

function fetchCalls() {
  return (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map(
    (call) => ({
      url: String(call[0]),
      method: (call[1] as RequestInit | undefined)?.method ?? "GET",
      body: (call[1] as RequestInit | undefined)?.body
        ? JSON.parse(String((call[1] as RequestInit).body))
        : undefined,
    }),
  );
}

beforeEach(() => {
  state.role = "teacher";
  state.push.mockClear();
  state.routes = [];
  const platform = new PlatformApi({ csrfToken: "c".repeat(32) });
  state.api = Object.assign(platform as unknown as Record<string, unknown>, {
    listCourseQuizzes: vi.fn().mockResolvedValue([]),
    listMyRecordAttempts: vi.fn().mockResolvedValue([]),
  });
  invalidateRequestCache(state.api);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const route = state.routes.find(
        (r) => r.match.test(url) && (r.method == null || r.method === method),
      );
      return new Response(JSON.stringify(route ? route.body : {}), {
        status: route ? (route.status ?? 200) : 404,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("teacher Hide results from students switch", () => {
  it("uses that exact label, defaults on, and treats a missing field as hidden", async () => {
    render(<QuizEditor />);
    const toggle = screen.getByRole("checkbox", {
      name: "Hide results from students",
    });
    expect((toggle as HTMLInputElement).checked).toBe(true);
    expect(
      screen.getByText(
        "Results are hidden from students by default. Turn this off to show students scores, correctness, and feedback.",
      ),
    ).toBeTruthy();

    state.routes.push(
      { match: /\/quizzes\/q-live$/, method: "GET", body: publishedQuiz },
      { match: /record-attempts/, body: [] },
    );
    cleanup();
    render(<QuizEditor quizId="q-live" />);
    const publishedToggle = await screen.findByRole("checkbox", {
      name: "Hide results from students",
    });
    expect((publishedToggle as HTMLInputElement).checked).toBe(true);
  });

  it("can change a published quiz through the visibility PUT, not a whole-quiz PATCH", async () => {
    const updated = { ...publishedQuiz, hide_results_from_students: false };
    state.routes.push(
      {
        match: /\/quizzes\/q-live$/,
        method: "GET",
        body: { ...publishedQuiz, hide_results_from_students: true },
      },
      { match: /record-attempts/, body: [] },
      {
        match: /student-results-visibility$/,
        method: "PUT",
        body: updated,
      },
    );
    render(<QuizEditor quizId="q-live" />);
    const toggle = await screen.findByRole("checkbox", {
      name: "Hide results from students",
    });
    fireEvent.click(toggle);
    await waitFor(() =>
      expect((toggle as HTMLInputElement).checked).toBe(false),
    );
    const calls = fetchCalls();
    const visibility = calls.filter((call) =>
      call.url.includes("/student-results-visibility"),
    );
    expect(visibility).toEqual([
      {
        url: expect.stringMatching(
          /\/api\/v1\/courses\/course-1\/quizzes\/q-live\/student-results-visibility$/,
        ),
        method: "PUT",
        body: { hide_results_from_students: false },
      },
    ]);
    expect(
      calls.filter(
        (call) =>
          call.method === "PATCH" &&
          /\/quizzes\/q-live$/.test(call.url) &&
          !call.url.includes("student-results-visibility"),
      ),
    ).toEqual([]);
  });
});

describe("teacher grading stays visible", () => {
  it("still shows scores, correctness, feedback and the key when results are hidden from students", async () => {
    state.routes.push(
      {
        method: "GET",
        match: /record-attempts/,
        body: [quizRow],
      },
      {
        method: "GET",
        match: /attempts\/att-1$/,
        body: attemptDetail("teacher", false),
      },
    );
    render(<QuizSubmissions courseId="course-1" quizId="quiz-1" />);
    const row = await screen.findByRole("button", { name: /^Ada/ });
    expect(row.textContent).toContain("3 / 6");
    expect(row.textContent).toContain("Needs grading");
    fireEvent.click(row);
    const sheet = await screen.findByTestId("quiz-attempt-detail");
    expect(within(sheet).getByLabelText("3 / 6")).toBeTruthy();
    expect(within(sheet).getByText("Correct")).toBeTruthy();
    expect(within(sheet).getByText("Name a second reason.")).toBeTruthy();
    expect(
      within(sheet).getByRole("columnheader", { name: "Key" }),
    ).toBeTruthy();
    expect(within(sheet).getByText("Mentions decoupling.")).toBeTruthy();
  });
});

describe("student results_visible", () => {
  it("hides scores when results_visible is false or missing, and does not render null as 0", async () => {
    state.role = "student";
    const hiddenRow = {
      ...quizRow,
      user_id: "user-1",
      results_visible: false,
    };
    const missingRow = {
      ...quizRow,
      attempt_id: "att-missing",
      title: "Week 2 Quiz",
      quiz_id: "quiz-2",
      score_objective: null,
      score_max_objective: null,
      points_awarded: null,
      points_total: null,
      grading_status: null,
    };
    delete (missingRow as { results_visible?: boolean }).results_visible;
    (state.api.listCourseQuizzes as ReturnType<typeof vi.fn>).mockResolvedValue(
      [],
    );
    (state.api.listMyRecordAttempts as ReturnType<typeof vi.fn>).mockResolvedValue([
      hiddenRow,
      missingRow,
    ]);
    state.routes.push({
      method: "GET",
      match: /attempts\/att-1$/,
      body: {
        ...attemptDetail("student", false),
        // Leak scores in the payload; the UI must still hide them.
        results_visible: false,
        score_objective: 3,
        score_max_objective: 3,
        points_awarded: 3,
        points_total: 6,
        grading_status: "complete",
      },
    });

    render(<StudentQuizList courseId="course-1" onStart={vi.fn()} />);
    const hidden = await screen.findByRole("button", { name: /Week 3 Quiz/ });
    expect(hidden.textContent).toContain("Results are not yet available.");
    expect(hidden.textContent).not.toContain("3 / 6");
    expect(hidden.textContent).not.toContain("0 /");
    expect(hidden.textContent).not.toMatch(/\b0\b/);
    expect(screen.queryByText("Graded")).toBeNull();
    expect(screen.queryByText("Not graded yet")).toBeNull();

    const missing = screen.getByRole("button", { name: /Week 2 Quiz/ });
    expect(missing.textContent).toContain("Results are not yet available.");
    expect(missing.textContent).not.toMatch(/\b0\b/);

    fireEvent.click(hidden);
    const sheet = await screen.findByTestId("quiz-attempt-detail");
    expect(within(sheet).getByText("API gateway")).toBeTruthy();
    expect(within(sheet).getByText("Decouple producers")).toBeTruthy();
    expect(within(sheet).queryByLabelText("3 / 6")).toBeNull();
    expect(within(sheet).queryByText("Correct")).toBeNull();
    expect(within(sheet).queryByText("Name a second reason.")).toBeNull();
    expect(within(sheet).queryByText("Not graded yet")).toBeNull();
    expect(
      within(sheet).queryByRole("columnheader", { name: "Key" }),
    ).toBeNull();
    expect(within(sheet).queryByText("API gateway / Database")).toBeNull();
  });

  it("shows scores when results_visible is true, but never the standard answer", async () => {
    state.role = "student";
    (state.api.listCourseQuizzes as ReturnType<typeof vi.fn>).mockResolvedValue(
      [],
    );
    (state.api.listMyRecordAttempts as ReturnType<typeof vi.fn>).mockResolvedValue([
      { ...quizRow, user_id: "user-1", results_visible: true },
    ]);
    state.routes.push({
      method: "GET",
      match: /attempts\/att-1$/,
      body: attemptDetail("student", true),
    });
    render(<StudentQuizList courseId="course-1" onStart={vi.fn()} />);
    const row = await screen.findByRole("button", { name: /Week 3 Quiz/ });
    expect(row.textContent).toContain("3 / 6");
    expect(row.textContent).toContain("Not graded yet");
    expect(row.textContent).not.toContain("Results are not yet available.");
    fireEvent.click(row);
    const sheet = await screen.findByTestId("quiz-attempt-detail");
    expect(within(sheet).getByLabelText("3 / 6")).toBeTruthy();
    expect(within(sheet).getByText("Correct")).toBeTruthy();
    expect(within(sheet).getByText("Name a second reason.")).toBeTruthy();
    expect(
      within(sheet).queryByRole("columnheader", { name: "Key" }),
    ).toBeNull();
    expect(within(sheet).queryByText("Mentions decoupling.")).toBeNull();
  });

  it("on the submit receipt, hides scores unless results_visible is true, and keeps the student's own answers", async () => {
    state.role = "student";
    const submit = vi.fn().mockResolvedValue({
      id: "att-1",
      quiz_id: "quiz-1",
      course_id: "course-1",
      actor_user_id: "user-1",
      content_revision: 1,
      status: "submitted",
      results_visible: false,
      submitted_at: "2026-11-08T01:00:00Z",
      answers: [
        { item_id: "q1", choice_ids: ["a"] },
        { item_id: "q3", text: "Decouple producers" },
      ],
    });
    render(
      <QuizTake
        courseId="course-1"
        quiz={studentQuiz}
        onExit={vi.fn()}
        api={{
          getStudentQuiz: vi.fn(),
          submitCourseQuizAttempt: submit,
        }}
      />,
    );
    fireEvent.click(screen.getByText("API gateway"));
    fireEvent.change(
      screen.getByLabelText("Name one reason to use a queue."),
      { target: { value: "Decouple producers" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Submitted")).toBeTruthy();
    expect(screen.getByText("Results are not yet available.")).toBeTruthy();
    expect(screen.getByText("API gateway")).toBeTruthy();
    expect(screen.getByText("Decouple producers")).toBeTruthy();
    expect(screen.queryByText(/Objective score/)).toBeNull();
    expect(screen.queryByText("3 / 6")).toBeNull();
    expect(screen.queryByText(/0 \//)).toBeNull();

    cleanup();
    submit.mockResolvedValue({
      id: "att-2",
      quiz_id: "quiz-1",
      course_id: "course-1",
      actor_user_id: "user-1",
      content_revision: 1,
      status: "submitted",
      results_visible: true,
      score_objective: 3,
      score_max_objective: 3,
      submitted_at: "2026-11-08T01:00:00Z",
      answers: [{ item_id: "q1", choice_ids: ["a"] }],
    });
    render(
      <QuizTake
        courseId="course-1"
        quiz={studentQuiz}
        onExit={vi.fn()}
        api={{
          getStudentQuiz: vi.fn(),
          submitCourseQuizAttempt: submit,
        }}
      />,
    );
    fireEvent.click(screen.getByText("API gateway"));
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(
      await screen.findByText("Objective score: 3 / 3 (100%)"),
    ).toBeTruthy();
    expect(screen.queryByText("Results are not yet available.")).toBeNull();
    expect(screen.queryByText("Key")).toBeNull();
  });

  it("does not treat a missing results_visible field on the receipt as a zero score", async () => {
    state.role = "student";
    render(
      <QuizTake
        courseId="course-1"
        quiz={studentQuiz}
        onExit={vi.fn()}
        api={{
          getStudentQuiz: vi.fn(),
          submitCourseQuizAttempt: vi.fn().mockResolvedValue({
            id: "att-3",
            quiz_id: "quiz-1",
            course_id: "course-1",
            actor_user_id: "user-1",
            content_revision: 1,
            status: "submitted",
            submitted_at: "2026-11-08T01:00:00Z",
            answers: [{ item_id: "q1", choice_ids: ["a"] }],
          }),
        }}
      />,
    );
    fireEvent.click(screen.getByText("API gateway"));
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Results are not yet available.")).toBeTruthy();
    expect(screen.queryByText(/Objective score/)).toBeNull();
    expect(screen.queryByText(/0 \//)).toBeNull();
  });
});

describe("teacher attempt detail ignores a hidden results_visible flag", () => {
  it("still renders the marked paper when the DTO omits results_visible", async () => {
    state.routes.push({
      method: "GET",
      match: /attempts\/att-1$/,
      body: attemptDetail("teacher"),
    });
    render(
      <QuizAttemptDetailView
        courseId="course-1"
        quizId="quiz-1"
        attemptId="att-1"
        teacher
      />,
    );
    const sheet = await screen.findByTestId("quiz-attempt-detail");
    expect(within(sheet).getByLabelText("3 / 6")).toBeTruthy();
    expect(within(sheet).getByRole("columnheader", { name: "Key" })).toBeTruthy();
  });
});
