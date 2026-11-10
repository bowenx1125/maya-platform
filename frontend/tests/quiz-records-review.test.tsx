import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QuizApi } from "../lib/api/quiz";
import { PlatformApi } from "../lib/api/platform";
import { localizeError } from "../lib/i18n";
import { invalidateRequestCache } from "../lib/request-cache";

const state = vi.hoisted(() => ({
  api: {} as Record<string, unknown>,
  role: "teacher" as "teacher" | "student",
  search: "",
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    identityGeneration: 1,
    user: {
      id: "user-1",
      courses: [{ course_id: "course-1", role: state.role }],
      groups: [],
    },
  }),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(state.search),
  usePathname: () => "/teacher/quizzes/quiz-1",
  useRouter: () => ({ push: vi.fn() }),
}));

import { QuizSubmissions } from "../components/quizzes/quiz-submissions";
import { StudentQuizList } from "../components/quiz/quiz-list";

type Call = { method: string; url: string; body?: unknown };
let calls: Call[] = [];
let routes: Array<{
  method: string;
  match: RegExp;
  reply: (call: Call) => Response;
}> = [];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

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

const chatRow = {
  ...quizRow,
  source: "chat",
  attempt_id: "chat-1",
  title: "Keynotes",
  quiz_id: null,
  team_name: "Keynotes",
  taking_epoch: null,
};

function detail(view: "teacher" | "student", graded = false) {
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
    grading_status: graded ? "complete" : "mixed",
    score_objective: 3,
    score_max_objective: 3,
    score_manual: graded ? 2 : 0,
    score_max_manual: 3,
    points_awarded: graded ? 5 : 3,
    points_total: 6,
    submitted_at: "2026-11-08T01:00:00Z",
    graded_at: graded ? "2026-11-08T02:00:00Z" : null,
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
        correct: true,
        points_awarded: 3,
        graded: true,
        ...(view === "teacher" ? { answer: { choice_ids: ["a"] } } : {}),
      },
      {
        id: "q3",
        type: "short_text",
        prompt: "Name one reason to use a queue.",
        choices: [],
        points: 3,
        response_text: "Decouple producers",
        graded,
        points_awarded: graded ? 2 : null,
        feedback: graded ? "Name a second reason." : null,
        ...(view === "teacher"
          ? { answer: { rubric: "Mentions decoupling." } }
          : {}),
      },
    ],
  };
}

beforeEach(() => {
  calls = [];
  routes = [];
  state.search = "";
  state.role = "teacher";
  const platform = new PlatformApi({ csrfToken: "c".repeat(32) });
  state.api = Object.assign(platform as unknown as Record<string, unknown>, {
    courseAssessmentAttempts: vi.fn().mockResolvedValue([
      {
        attempt_id: "chat-1",
        user_id: "student-1",
        student_name: "Ada",
        test_name: "Keynotes · Formal diagnostic questions · V1.0",
        team_name: "Keynotes",
        status: "completed",
        phase: "completed",
        conversation_id: null,
        group_name: "Group A",
        started_at: "2026-10-13T08:00:00Z",
        ended_at: "2026-10-13T08:20:00Z",
        points_awarded: 1,
        points_total: 1,
        questions: [],
        report_download_path: null,
      },
    ]),
    myAssessmentAttempts: vi.fn().mockResolvedValue([]),
    deleteCourseAssessmentAttempt: vi.fn().mockResolvedValue(undefined),
    listMyRecordAttempts: vi.fn().mockResolvedValue([quizRow, chatRow]),
    listCourseQuizzes: vi.fn().mockResolvedValue([]),
  });
  invalidateRequestCache(state.api);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const call: Call = {
        method,
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      };
      calls.push(call);
      const route = routes.find(
        (candidate) => candidate.method === method && candidate.match.test(url),
      );
      return route ? route.reply(call) : json({ code: "not_found" }, 404);
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("QuizApi errors", () => {
  it("keeps the backend's top-level code so teachers get English copy", async () => {
    routes.push({
      method: "POST",
      match: /start-taking$/,
      reply: () =>
        json(
          {
            code: "quiz_taking_already_open",
            message: "The quiz is already open for taking.",
            details: {},
            request_id: "r",
          },
          409,
        ),
    });
    const api = new QuizApi(new PlatformApi());
    const caught = await api.startTaking("c", "q").catch((error) => error);
    expect(caught.code).toBe("quiz_taking_already_open");
    expect(caught.status).toBe(409);
    expect(localizeError(caught)).toBe("Taking is already open.");
  });

  it("falls back to an HTTP message when the body is not JSON", async () => {
    routes.push({
      method: "POST",
      match: /pause-taking$/,
      reply: () => new Response("<html>bad gateway</html>", { status: 502 }),
    });
    const caught = await new QuizApi(new PlatformApi())
      .pauseTaking("c", "q")
      .catch((error) => error);
    expect(caught.code).toBeUndefined();
    expect(caught.message).not.toContain("<html>");
  });
});

describe("teacher Quiz Submissions tab", () => {
  const second = {
    ...quizRow,
    attempt_id: "att-2",
    student_name: "Ben",
    taking_epoch: 1,
    grading_status: "complete",
    points_awarded: 5,
  };
  beforeEach(() => {
    routes.push(
      {
        method: "GET",
        match: /record-attempts/,
        reply: () => json([quizRow, second, chatRow]),
      },
      {
        method: "GET",
        match: /attempts\/att-1$/,
        reply: () => json(detail("teacher")),
      },
      {
        method: "PUT",
        match: /attempts\/att-1\/grades$/,
        reply: () => json(detail("teacher", true)),
      },
      {
        method: "DELETE",
        match: /attempts\/att-1$/,
        reply: () => new Response(null, { status: 204 }),
      },
    );
  });

  const renderTab = () =>
    render(<QuizSubmissions courseId="course-1" quizId="quiz-1" />);

  it("lists this quiz's attempts by student with round, state and score, and no chat rows", async () => {
    renderTab();
    const row = await screen.findByRole("button", { name: /^Ada/ });
    expect(row.textContent).toContain("Round 2");
    expect(row.textContent).toContain("Needs grading");
    expect(row.textContent).toContain("3 / 6");
    expect(screen.getByRole("button", { name: /^Ben/ })).toBeTruthy();
    expect(screen.queryByText("Keynotes")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Record" })).toBeNull();
  });

  it("filters by round and by what still needs grading", async () => {
    renderTab();
    await screen.findByRole("button", { name: /^Ada/ });
    const group = screen.getByRole("group", { name: "Filter submissions" });
    fireEvent.click(within(group).getByRole("button", { name: "Round 1" }));
    expect(screen.queryByRole("button", { name: /^Ada/ })).toBeNull();
    expect(screen.getByRole("button", { name: /^Ben/ })).toBeTruthy();
    fireEvent.click(
      within(group).getByRole("button", { name: "Needs grading · 1" }),
    );
    expect(screen.getByRole("button", { name: /^Ada/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Ben/ })).toBeNull();
  });

  it("grades a text question by hand and shows the key", async () => {
    renderTab();
    const row = await screen.findByRole("button", { name: /^Ada/ });
    fireEvent.click(row);
    const sheet = await screen.findByTestId("quiz-attempt-detail");
    expect(within(sheet).getByText("Mentions decoupling.")).toBeTruthy();
    // The row carries the grading state; the opened paper does not repeat it.
    expect(within(sheet).queryByText("Needs grading")).toBeNull();
    fireEvent.change(
      within(sheet).getByRole("spinbutton", { name: "Points for question 2" }),
      { target: { value: "2" } },
    );
    fireEvent.change(
      within(sheet).getByRole("textbox", { name: "Feedback for question 2" }),
      { target: { value: "Name a second reason." } },
    );
    fireEvent.click(within(sheet).getByRole("button", { name: "Save grades" }));
    expect(await screen.findByText("Grades saved.")).toBeTruthy();
    const put = calls.find((call) => call.method === "PUT");
    expect(put?.body).toEqual({
      grades: [
        {
          item_id: "q3",
          points_awarded: 2,
          feedback: "Name a second reason.",
        },
      ],
    });
  });

  it("hides an attempt only after a confirm", async () => {
    const confirm = vi.spyOn(window, "confirm");
    renderTab();
    fireEvent.click(await screen.findByRole("button", { name: /^Ada/ }));
    const hide = await screen.findByRole("button", {
      name: "Hide Ada's attempt",
    });
    confirm.mockReturnValueOnce(false);
    fireEvent.click(hide);
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
    confirm.mockReturnValueOnce(true);
    fireEvent.click(hide);
    await waitFor(() =>
      expect(calls.some((call) => call.method === "DELETE")).toBe(true),
    );
  });

  it("marks only AI-graded items, pending until a score arrives", async () => {
    routes[1] = {
      method: "GET",
      match: /attempts\/att-1$/,
      reply: () =>
        json({
          ...detail("teacher"),
          items: detail("teacher").items.map((item) =>
            item.id === "q3"
              ? { ...item, graded: false, ai_score: null, ai_grading: true }
              : item,
          ),
        }),
    };
    renderTab();
    const row = await screen.findByRole("button", { name: /^Ada/ });
    // One status on the row; no AI totals or extra status chips.
    expect(row.textContent).toContain("Needs grading");
    expect(row.textContent).not.toMatch(/AI|Mixed|Pending/);
    fireEvent.click(row);
    const sheet = await screen.findByTestId("quiz-attempt-detail");
    expect(within(sheet).getByTestId("quiz-item-ai-q3").textContent).toBe(
      "AI score pending",
    );
    expect(within(sheet).queryByTestId("quiz-item-ai-q1")).toBeNull();
    expect(within(sheet).queryByText(/Mixed|Complete/)).toBeNull();
  });

  it("shows a selection as correct when the choice question has no standard answer", async () => {
    routes[1] = {
      method: "GET",
      match: /attempts\/att-1$/,
      reply: () =>
        json({
          ...detail("teacher"),
          points_awarded: 0,
          points_total: 3,
          items: [
            {
              id: "q-open",
              type: "multiple",
              prompt: "Pick anything",
              choices: [
                { id: "a", label: "One" },
                { id: "b", label: "Two" },
              ],
              points: 3,
              response_choice_ids: ["b"],
              correct: false,
              points_awarded: 0,
              graded: true,
              answer: { choice_ids: [] },
            },
          ],
        }),
    };
    renderTab();
    fireEvent.click(await screen.findByRole("button", { name: /^Ada/ }));
    const sheet = await screen.findByTestId("quiz-attempt-detail");
    expect(within(sheet).getByText("Correct")).toBeTruthy();
    expect(within(sheet).queryByText("Incorrect")).toBeNull();
    expect(within(sheet).getByLabelText("3 / 3")).toBeTruthy();
    expect(sheet.textContent).toContain("3 / 3");
  });

  it("shows the AI score beside the editable points once it arrives", async () => {
    routes[1] = {
      method: "GET",
      match: /attempts\/att-1$/,
      reply: () =>
        json({
          ...detail("teacher", true),
          score_ai: 2,
          items: detail("teacher", true).items.map((item) =>
            item.id === "q3"
              ? { ...item, ai_score: 2, ai_grading: true }
              : item,
          ),
        }),
    };
    renderTab();
    fireEvent.click(await screen.findByRole("button", { name: /^Ada/ }));
    const sheet = await screen.findByTestId("quiz-attempt-detail");
    expect(within(sheet).getByTestId("quiz-item-ai-q3").textContent).toBe(
      "AI 2 / 3",
    );
    // The teacher can still overrule it.
    expect(
      within(sheet).getByRole("spinbutton", { name: "Points for question 2" }),
    ).toBeTruthy();
  });
});

describe("student Quiz list", () => {
  it("puts own results in the one list, opens them without the key, and shows no chat Record", async () => {
    state.role = "student";
    (state.api.listCourseQuizzes as ReturnType<typeof vi.fn>).mockResolvedValue(
      [
        {
          id: "quiz-open",
          course_id: "course-1",
          group_id: null,
          title: "Week 9 Quiz",
          status: "published",
          schema_version: 1,
          content_revision: 1,
          attempt_count: 0,
          taking_open: true,
          taking_epoch: 1,
          created_by_user_id: "t",
          published_at: null,
          created_at: "",
          updated_at: "",
        },
        {
          id: "quiz-1",
          course_id: "course-1",
          group_id: null,
          title: "Week 3 Quiz",
          status: "published",
          schema_version: 1,
          content_revision: 1,
          attempt_count: 1,
          taking_open: false,
          taking_epoch: 2,
          created_by_user_id: "t",
          published_at: null,
          created_at: "",
          updated_at: "",
        },
      ],
    );
    routes.push({
      method: "GET",
      match: /attempts\/att-1$/,
      reply: () => json(detail("student")),
    });
    const onStart = vi.fn();
    render(<StudentQuizList courseId="course-1" onStart={onStart} />);
    fireEvent.click(await screen.findByRole("button", { name: "Start" }));
    expect(onStart).toHaveBeenCalledWith(
      expect.objectContaining({ id: "quiz-open" }),
    );
    // Taken and closed: shown once, as its result, not as "Not open yet".
    expect(screen.queryByTestId("quiz-not-open")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Week 3 Quiz/ }));
    const sheet = await screen.findByTestId("quiz-attempt-detail");
    expect(
      within(sheet).queryByRole("columnheader", { name: "Key" }),
    ).toBeNull();
    expect(within(sheet).getByText("Not graded yet")).toBeTruthy();
    expect(within(sheet).getByText("Correct")).toBeTruthy();
    expect(within(sheet).queryByRole("button", { name: /Hide/ })).toBeNull();
    expect(screen.queryByText("Keynotes")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Record" })).toBeNull();
  });
});
