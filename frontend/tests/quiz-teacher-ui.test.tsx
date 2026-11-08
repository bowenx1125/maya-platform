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

// Owner pick (2026-11-08, second round): option A "one page per quiz". The
// list rows carry no keys; a quiz page has Paper | Submissions. B's LIVE lamp
// and dashed "Add question" slot stay.
const state = vi.hoisted(() => ({
  push: vi.fn(),
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
  useRouter: () => ({ push: state.push }),
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
  it("shows one state chip per row, the LIVE lamp only while accepting, and no row keys", async () => {
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

    // Rows are links to the quiz page and hold no keys of their own.
    for (const row of rows) {
      expect(within(row).queryByRole("button")).toBeNull();
      expect(within(row).queryByRole("link")).toBeNull();
    }
    expect(live.getAttribute("href")).toBe("/teacher/quizzes/q-live");
    expect(draft.getAttribute("href")).toBe("/teacher/quizzes/q-draft");

    expect(within(live).getByText("LIVE")).toBeTruthy();
    expect(within(live).getByText("Accepting submissions")).toBeTruthy();
    expect(within(live).getByText("12 attempts")).toBeTruthy();
    expect(within(paused).getByText("Paused")).toBeTruthy();
    expect(within(paused).queryByText("LIVE")).toBeNull();
    expect(within(draft).getByText("Draft")).toBeTruthy();
    expect(within(draft).queryByText(/attempts/)).toBeNull();
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
  it("a new quiz is Paper only: title typed in the banner, Submissions locked", async () => {
    render(<QuizEditor />);
    const tabs = screen.getByRole("tablist", { name: "Quiz" });
    expect(
      within(tabs)
        .getByRole("tab", { name: "Paper" })
        .getAttribute("aria-selected"),
    ).toBe("true");
    const submissions = within(tabs).getByRole("tab", { name: /Submissions/ });
    expect(submissions.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(submissions);
    expect(submissions.getAttribute("aria-selected")).toBe("false");
    expect(screen.getByLabelText("Title")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Done" })).toBeTruthy();
    expect(screen.getByText("Draft")).toBeTruthy();
  });

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

  it("opens a published quiz on Submissions; its Paper is read-only with Unpublish", async () => {
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
    state.routes.push({ match: /record-attempts/, body: [] });
    render(<QuizEditor quizId="q-live" />);
    // A published quiz opens on its record.
    const tabs = await screen.findByRole("tablist", { name: "Quiz" });
    const submissions = within(tabs).getByRole("tab", { name: /Submissions/ });
    expect(submissions.getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByText("No records yet.")).toBeTruthy();
    expect(screen.getByText("LIVE")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Pause evaluation" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download" })).toBeTruthy();
    // Back + Done stay as a pair; with nothing to save, Done returns.
    expect(screen.getByRole("link", { name: "Back" })).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Done" }).getAttribute("href"),
    ).toBe("/teacher/quizzes");

    fireEvent.click(within(tabs).getByRole("tab", { name: "Paper" }));
    expect(
      screen.getByText("Unpublish this quiz before editing it."),
    ).toBeTruthy();
    expect(screen.queryByLabelText("Prompt")).toBeNull();
    expect(screen.queryByLabelText("Title")).toBeNull();
    expect(screen.getByText("Which layer handles auth?")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Unpublish" })).toBeTruthy();
  });
});

describe("teacher Quiz delete", () => {
  it("deletes the quiz and its Record for good, only after a confirm", async () => {
    state.routes.push(
      { match: /record-attempts/, body: [] },
      {
        match: /\/quizzes\/q-live$/,
        body: {
          ...base,
          id: "q-live",
          title: "Week 9",
          status: "published",
          taking_open: true,
          attempt_count: 2,
          settings: {},
          items: [],
        },
      },
    );
    render(<QuizEditor quizId="q-live" />);
    const tabs = await screen.findByRole("tablist", { name: "Quiz" });
    // Delete sits at the foot of the Paper, not on Submissions.
    expect(screen.queryByTestId("quiz-delete")).toBeNull();
    fireEvent.click(within(tabs).getByRole("tab", { name: "Paper" }));
    const remove = screen.getByRole("button", { name: "Delete quiz" });
    const fetchMock = vi.mocked(globalThis.fetch);
    const deletes = () =>
      fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE");
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    fireEvent.click(remove);
    expect(confirm.mock.calls[0][0]).toContain("Week 9");
    expect(deletes()).toHaveLength(0);
    confirm.mockReturnValueOnce(true);
    fireEvent.click(remove);
    await waitFor(() => expect(deletes()).toHaveLength(1));
    expect(String(deletes()[0][0])).toMatch(
      /\/courses\/course-1\/quizzes\/q-live$/,
    );
    await waitFor(() =>
      expect(state.push).toHaveBeenCalledWith("/teacher/quizzes"),
    );
    confirm.mockRestore();
  });
});
