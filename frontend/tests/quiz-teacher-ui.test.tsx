import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformApi } from "../lib/api/platform";

// Owner pick (2026-11-08): option A for the teacher Quiz pages, with B's
// LIVE lamp and B's dashed "Add question" slot in A's colours.
const state = vi.hoisted(() => ({
  api: {} as unknown,
  routes: [] as Array<{ match: RegExp; body: unknown }>,
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    identityGeneration: 1,
    user: {
      id: "teacher-1",
      courses: [{ course_id: "course-1", role: "teacher" }],
      groups: [],
    },
  }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/teacher/quizzes",
  useSearchParams: () => new URLSearchParams(),
}));

import { QuizzesList } from "../components/quizzes/quizzes-list";
import QuizEditor from "../components/quizzes/quiz-editor";

const base = {
  course_id: "course-1",
  schema_version: 1,
  content_revision: 1,
  created_by_user_id: "teacher-1",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-08T00:00:00Z",
};

beforeEach(() => {
  state.api = new PlatformApi({ csrfToken: "c".repeat(32) });
  state.routes = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const route = state.routes.find((r) => r.match.test(url));
      return new Response(JSON.stringify(route ? route.body : {}), {
        status: route ? 200 : 404,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("teacher Quizzes list", () => {
  it("shows one status pill per quiz, the LIVE lamp only while accepting, and symbol+word keys", async () => {
    state.routes.push({
      match: /\/quizzes$/,
      body: [
        {
          ...base,
          id: "q-live",
          title: "Week 9",
          status: "published",
          taking_open: true,
          attempt_count: 12,
        },
        {
          ...base,
          id: "q-paused",
          title: "Week 8",
          status: "published",
          taking_open: false,
          attempt_count: 28,
        },
        {
          ...base,
          id: "q-draft",
          title: "Week 10",
          status: "draft",
          attempt_count: 0,
        },
      ],
    });
    render(<QuizzesList />);
    const rows = await screen.findAllByTestId("quiz-row");
    expect(rows).toHaveLength(3);
    const [live, paused, draft] = rows;

    expect(within(live).getByText("Accepting submissions")).toBeTruthy();
    expect(within(live).getByText("LIVE")).toBeTruthy();
    expect(
      within(live).getByRole("button", { name: "Pause evaluation" }),
    ).toBeTruthy();

    expect(within(paused).getByText("Published · Paused")).toBeTruthy();
    expect(within(paused).queryByText("LIVE")).toBeNull();
    const start = within(paused).getByRole("button", {
      name: "Start evaluation",
    });
    expect(start.querySelector("svg")).not.toBeNull();

    expect(within(draft).getByText("Draft")).toBeTruthy();
    expect(within(draft).queryByRole("button")).toBeNull();
    const records = within(draft).getByRole("link", { name: "Records" });
    expect(records.querySelector("svg")).not.toBeNull();
    expect(records.getAttribute("href")).toBe(
      "/teacher/quizzes/records?quiz_id=q-draft",
    );
  });

  it("shows the sticker empty card only when the list is really empty", async () => {
    state.routes.push({ match: /\/quizzes$/, body: [] });
    render(<QuizzesList />);
    expect(
      await screen.findByRole("heading", { name: "No Quizzes yet." }),
    ).toBeTruthy();
  });
});

describe("teacher Quiz editor", () => {
  it("adds questions from the dashed slot and steps points", async () => {
    render(<QuizEditor />);
    expect(screen.getByRole("heading", { name: "Add question" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Single choice" }));
    expect(screen.getByText("#01")).toBeTruthy();
    const points = screen.getByLabelText("Points") as HTMLInputElement;
    expect(points.value).toBe("1");
    fireEvent.click(screen.getByRole("button", { name: "More points" }));
    expect(points.value).toBe("2");
    fireEvent.click(screen.getByRole("button", { name: "Fewer points" }));
    fireEvent.click(screen.getByRole("button", { name: "Fewer points" }));
    expect(points.value).toBe("0");
    expect(
      (
        screen.getByRole("button", {
          name: "Fewer points",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    const marks = screen.getAllByLabelText("Mark as correct answer");
    expect(marks).toHaveLength(2);
    fireEvent.click(marks[0]);
    expect((marks[0] as HTMLInputElement).checked).toBe(true);
  });

  it("shows a published quiz read-only with the lock notice and LIVE lamp", async () => {
    state.routes.push({
      match: /\/quizzes\/q-live$/,
      body: {
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
      },
    });
    render(<QuizEditor quizId="q-live" />);
    expect(
      await screen.findByText("Unpublish this quiz before editing it."),
    ).toBeTruthy();
    expect(screen.getByText("LIVE")).toBeTruthy();
    expect(screen.queryByLabelText("Prompt")).toBeNull();
    expect(screen.getByText("Which layer handles auth?")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Pause evaluation" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Unpublish" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Done" })).toBeNull();
  });
});
