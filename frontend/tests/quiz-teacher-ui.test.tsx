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

// Owner pick (2026-11-08, second round): option A "one page per quiz".
// A quiz page has Paper | Submissions. Delete quiz is a list-row key.
// B's LIVE lamp and dashed "Add question" slot stay.
const state = vi.hoisted(() => ({
  push: vi.fn(),
  api: {} as unknown,
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
  state.push.mockClear();
  state.routes = [];
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
});

describe("teacher Quizzes list", () => {
  it("shows one state chip per row and the LIVE lamp only while accepting", async () => {
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

    // The row link opens the quiz. Delete quiz is a sibling key, not inside it.
    for (const row of rows) {
      expect(within(row).queryByRole("button")).toBeNull();
      expect(within(row).queryByRole("link")).toBeNull();
      const item = row.closest("li");
      expect(item).toBeTruthy();
      expect(
        within(item as HTMLElement).getByRole("button", {
          name: "Delete quiz",
        }),
      ).toBeTruthy();
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
    // Clicking the selected single-choice mark clears it.
    fireEvent.click(marks[0]);
    expect((marks[0] as HTMLInputElement).checked).toBe(false);
  });

  it("publishes a choice question that has no marked answer", async () => {
    state.routes.push(
      {
        method: "POST",
        match: /\/quizzes\/q-open\/publish$/,
        body: { id: "q-open", status: "published" },
      },
      {
        method: "POST",
        match: /\/quizzes$/,
        body: { id: "q-open", title: "Open", status: "draft" },
      },
    );
    render(<QuizEditor />);
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Open quiz" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Single choice" }));
    fireEvent.change(screen.getByLabelText("Prompt"), {
      target: { value: "Pick any" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(state.push).toHaveBeenCalledWith("/teacher/quizzes"),
    );
    expect(
      screen.queryByText(
        "Every choice question needs at least one marked answer.",
      ),
    ).toBeNull();
    const create = (
      globalThis.fetch as ReturnType<typeof vi.fn>
    ).mock.calls.find(
      (call) =>
        String(call[0]).endsWith("/quizzes") &&
        (call[1] as RequestInit | undefined)?.method === "POST",
    );
    const body = JSON.parse(String((create?.[1] as RequestInit).body));
    expect(body.items[0].answer).toEqual({ choice_ids: [] });
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
  const listBody = [
    {
      ...base,
      id: "q-live",
      title: "Week 9",
      status: "published",
      taking_open: true,
      attempt_count: 2,
    },
    {
      ...base,
      id: "q-draft",
      title: "Week 10",
      status: "draft",
      attempt_count: 0,
    },
  ];

  function deleteButton(title: string): HTMLElement {
    const row = screen.getByRole("link", { name: new RegExp(title) });
    const item = row.closest("li");
    if (!item) throw new Error(`no row for ${title}`);
    const button = within(item).getByRole("button", { name: "Delete quiz" });
    expect(button.closest("a")).toBeNull();
    return button;
  }

  it("is on each list row and absent from the quiz page", async () => {
    state.routes.push({ match: /\/quizzes$/, body: listBody });
    const list = render(<QuizzesList />);
    expect(await screen.findAllByTestId("quiz-delete")).toHaveLength(2);
    list.unmount();

    state.routes.push(
      { match: /record-attempts/, body: [] },
      {
        match: /\/quizzes\/q-live$/,
        body: {
          ...listBody[0],
          settings: {},
          items: [],
        },
      },
    );
    render(<QuizEditor quizId="q-live" />);
    const tabs = await screen.findByRole("tablist", { name: "Quiz" });
    expect(screen.queryByRole("button", { name: "Delete quiz" })).toBeNull();
    fireEvent.click(within(tabs).getByRole("tab", { name: "Paper" }));
    expect(screen.queryByRole("button", { name: "Delete quiz" })).toBeNull();
    expect(screen.queryByTestId("quiz-delete")).toBeNull();
  });

  it("deletes one row only after confirm, and leaves it when cancelled or refused", async () => {
    state.routes.push(
      { match: /\/quizzes$/, body: listBody },
      {
        match: /\/quizzes\/q-live$/,
        method: "DELETE",
        status: 200,
        body: {},
      },
    );
    render(<QuizzesList />);
    await screen.findByText("Week 9");
    const remove = deleteButton("Week 9");
    const fetchMock = vi.mocked(globalThis.fetch);
    const deletes = () =>
      fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE");
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    fireEvent.click(remove);
    expect(confirm.mock.calls[0][0]).toContain("Week 9");
    expect(deletes()).toHaveLength(0);
    expect(screen.getByText("Week 9")).toBeTruthy();
    expect(state.push).not.toHaveBeenCalled();

    confirm.mockReturnValueOnce(true);
    fireEvent.click(remove);
    await waitFor(() => expect(deletes()).toHaveLength(1));
    expect(String(deletes()[0][0])).toMatch(
      /\/courses\/course-1\/quizzes\/q-live$/,
    );
    await waitFor(() => expect(screen.queryByText("Week 9")).toBeNull());
    expect(screen.getByText("Week 10")).toBeTruthy();
    expect(state.push).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("keeps the row when the delete is refused, and ignores a second click", async () => {
    state.routes.push({ match: /\/quizzes$/, body: listBody });
    let started = 0;
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (method === "DELETE") {
          started += 1;
          await gate;
          return new Response(
            JSON.stringify({ message: "Could not delete." }),
            {
              status: 500,
              headers: { "Content-Type": "application/json" },
            },
          );
        }
        const route = state.routes.find((r) => r.match.test(url));
        return new Response(JSON.stringify(route ? route.body : {}), {
          status: route ? 200 : 404,
          headers: { "Content-Type": "application/json" },
        });
      },
    );
    render(<QuizzesList />);
    await screen.findByText("Week 9");
    const remove = deleteButton("Week 9");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(remove);
    fireEvent.click(remove);
    expect(started).toBe(1);
    release?.();
    await waitFor(() =>
      expect(
        screen.getByText(
          "Something went wrong on the server. Please try again.",
        ),
      ).toBeTruthy(),
    );
    expect(screen.getByText("Week 9")).toBeTruthy();
    expect(screen.getByText("Week 10")).toBeTruthy();
    expect(state.push).not.toHaveBeenCalled();
    confirm.mockRestore();
  });
});
