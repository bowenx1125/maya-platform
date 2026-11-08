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
  usePathname: () => "/teacher/quizzes/records",
  useRouter: () => ({ push: vi.fn() }),
}));

import QuizRecords from "../components/quizzes/quiz-records";
import { QuizRecords as StudentQuizRecords } from "../components/quiz/quiz-records";

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

describe("teacher Quiz Records", () => {
  beforeEach(() => {
    routes.push(
      {
        method: "GET",
        match: /record-attempts/,
        reply: () => json([quizRow, chatRow]),
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

  it("lists quiz submissions with their round and moves chat Record below", async () => {
    render(<QuizRecords />);
    const row = await screen.findByRole("button", { name: /Week 3 Quiz/ });
    expect(row.textContent).toContain("Round 2");
    expect(screen.queryByRole("button", { name: /^Keynotes/ })).toBeNull();
    expect(
      await screen.findByRole("button", {
        name: "Open the Record for Keynotes",
      }),
    ).toBeTruthy();
  });

  it("grades a text question by hand and shows the key", async () => {
    render(<QuizRecords />);
    fireEvent.click(await screen.findByRole("button", { name: /Week 3 Quiz/ }));
    const sheet = await screen.findByTestId("quiz-attempt-detail");
    expect(within(sheet).getByText("Mentions decoupling.")).toBeTruthy();
    expect(within(sheet).getByText("Needs grading")).toBeTruthy();
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
    render(<QuizRecords />);
    fireEvent.click(await screen.findByRole("button", { name: /Week 3 Quiz/ }));
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

  it("scoped to one quiz shows no chat Record board", async () => {
    state.search = "quiz_id=quiz-1";
    render(<QuizRecords />);
    await screen.findByRole("button", { name: /Week 3 Quiz/ });
    expect(screen.queryByRole("heading", { name: "Record" })).toBeNull();
  });
});

describe("student Quiz Records", () => {
  it("shows own answers and grades without the key, then own chat Record", async () => {
    state.role = "student";
    routes.push({
      method: "GET",
      match: /attempts\/att-1$/,
      reply: () => json(detail("student")),
    });
    render(<StudentQuizRecords courseId="course-1" />);
    fireEvent.click(await screen.findByRole("button", { name: /Week 3 Quiz/ }));
    const sheet = await screen.findByTestId("quiz-attempt-detail");
    expect(
      within(sheet).queryByRole("columnheader", { name: "Key" }),
    ).toBeNull();
    expect(within(sheet).getByText("Not graded yet")).toBeTruthy();
    expect(within(sheet).getByText("(Correct)")).toBeTruthy();
    expect(within(sheet).queryByRole("button", { name: /Hide/ })).toBeNull();
    expect(screen.getByRole("heading", { name: "Record" })).toBeTruthy();
    expect(
      state.api.myAssessmentAttempts as ReturnType<typeof vi.fn>,
    ).toHaveBeenCalledWith("course-1");
  });
});
