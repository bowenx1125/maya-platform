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
import { QuizzesList } from "../components/quizzes/quizzes-list";
import { QuizEditor } from "../components/quizzes/quiz-editor";
import { StudentQuizList } from "../components/quiz/quiz-list";

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

const base = {
  show_results: false,
  course_id: "course-1",
  schema_version: 1,
  content_revision: 1,
  created_by_user_id: "teacher-1",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-08T00:00:00Z",
};

const pausedQuiz = {
  ...base,
  id: "q-paused",
  title: "Week 8",
  status: "published",
  taking_open: false,
  taking_epoch: 2,
  exemption_count: 0,
  attempt_count: 1,
};

const exemptions = {
  taking_epoch: 2,
  exemptions: [],
  students: [
    {
      student_id: "s-1",
      username: "alice",
      display_name: "Alice Chen",
      submitted: false,
      exempt_until: null,
    },
    {
      student_id: "s-2",
      username: "bram",
      display_name: "Bram Okafor",
      submitted: true,
      exempt_until: null,
    },
  ],
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

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
      return jsonResponse(
        route ? route.body : {},
        route ? (route.status ?? 200) : 404,
      );
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("teacher list extend and schedule", () => {
  it("joins the clock to Start and opens the S2 popover", async () => {
    state.routes.push({
      match: /\/quizzes$/,
      body: [
        {
          ...base,
          id: "q-paused",
          title: "Week 8",
          status: "published",
          taking_open: false,
          taking_epoch: 2,
          exemption_count: 2,
          scheduled_start_at: "2026-11-12T01:00:00.000Z",
          scheduled_end_at: "2026-11-12T03:00:00.000Z",
          attempt_count: 4,
        },
      ],
    });
    render(<QuizzesList />);
    expect(await screen.findByText("Week 8")).toBeTruthy();
    expect(screen.getByText("2 extended")).toBeTruthy();
    expect(screen.getByText("Opens Nov 12, 09:00")).toBeTruthy();
    expect(screen.getByText("Closes Nov 12, 11:00")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Start evaluation" }),
    ).toBeTruthy();
    fireEvent.click(screen.getByTestId("quiz-schedule"));
    expect(
      await screen.findByRole("dialog", { name: "Schedule" }),
    ).toBeTruthy();
    expect(screen.getByLabelText("Start evaluation at")).toBeTruthy();
    expect(screen.getByLabelText("Pause evaluation at")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Save schedule" })).toBeTruthy();
    expect(
      screen.queryByText("Set either time or both. Each runs once."),
    ).toBeNull();
    expect(screen.getByLabelText("About Schedule")).toBeTruthy();
  });

  it("opens the inline extend panel and hides the helper paragraph", async () => {
    state.routes.push(
      {
        match: /\/quizzes$/,
        body: [pausedQuiz],
      },
      {
        match: /\/exemptions$/,
        method: "GET",
        body: exemptions,
      },
    );
    render(<QuizzesList />);
    fireEvent.click(await screen.findByTestId("quiz-extend"));
    expect(
      await screen.findByRole("heading", { name: "Extend time" }),
    ).toBeTruthy();
    expect(screen.getByLabelText("Search students")).toBeTruthy();
    expect(await screen.findByText("Alice Chen")).toBeTruthy();
    expect(screen.getByText("Submitted")).toBeTruthy();
    expect(
      screen.queryByText(
        "Students you pick can keep taking this quiz after you pause it, until the deadline.",
      ),
    ).toBeNull();
    expect(screen.getByLabelText("About Extend time")).toBeTruthy();
    const submitted = screen.getByText("Bram Okafor").closest("label");
    expect(
      (
        within(submitted as HTMLElement).getByRole(
          "checkbox",
        ) as HTMLInputElement
      ).disabled,
    ).toBe(true);
  });

  it.each([200, 500])(
    "shows four decorative skeleton rows until exemptions settle with status %i",
    async (status) => {
      state.routes.push({ match: /\/quizzes$/, body: [pausedQuiz] });
      render(<QuizzesList />);
      const extend = await screen.findByTestId("quiz-extend");
      let settle!: (response: Response) => void;
      const pending = new Promise<Response>((resolve) => {
        settle = resolve;
      });
      vi.mocked(fetch).mockImplementationOnce(() => pending);
      fireEvent.click(extend);

      const skeletons = screen.getAllByTestId("exemption-skeleton-row");
      expect(skeletons).toHaveLength(4);
      const list = skeletons[0].closest("ul")!;
      expect(list.getAttribute("aria-busy")).toBe("true");
      for (const row of skeletons) {
        expect(row.tagName).toBe("LI");
        expect(row.getAttribute("aria-hidden")).toBe("true");
      }
      expect(within(list).queryAllByRole("listitem")).toHaveLength(0);
      expect(within(list).queryAllByRole("checkbox")).toHaveLength(0);
      await waitFor(() =>
        expect(fetch).toHaveBeenCalledWith(
          expect.stringMatching(/\/exemptions$/),
          expect.anything(),
        ),
      );

      settle(jsonResponse(status === 200 ? exemptions : {}, status));
      await waitFor(() => {
        expect(screen.queryAllByTestId("exemption-skeleton-row")).toHaveLength(
          0,
        );
        expect(list.getAttribute("aria-busy")).toBe("false");
      });
      if (status === 200) {
        expect(within(list).getByText("Alice Chen")).toBeTruthy();
        expect(within(list).getByText("@alice")).toBeTruthy();
        expect(within(list).getByText("Bram Okafor")).toBeTruthy();
        expect(within(list).getAllByRole("checkbox")).toHaveLength(2);
      } else {
        expect(within(list).queryAllByRole("listitem")).toHaveLength(0);
      }
    },
  );

  it("disables Extend time before the first start, with a reason", async () => {
    state.routes.push({
      match: /\/quizzes$/,
      body: [
        {
          ...base,
          id: "q-new",
          title: "Week 11",
          status: "published",
          taking_open: false,
          taking_epoch: 0,
          attempt_count: 0,
        },
      ],
    });
    render(<QuizzesList />);
    const key = await screen.findByTestId("quiz-extend");
    expect((key as HTMLButtonElement).disabled).toBe(true);
    expect(
      key.closest("[data-ui-guide-text]")?.getAttribute("data-ui-guide-text"),
    ).toBe("Start taking once before extending time.");
    expect(screen.queryByTestId("quiz-extended-badge")).toBeNull();
  });

  it("hides taking controls on a draft row", async () => {
    state.routes.push({
      match: /\/quizzes$/,
      body: [
        {
          ...base,
          id: "q-draft",
          title: "Week 10",
          status: "draft",
          taking_epoch: 0,
          attempt_count: 0,
        },
      ],
    });
    render(<QuizzesList />);
    await screen.findByText("Week 10");
    expect(screen.queryByTestId("quiz-extend")).toBeNull();
    expect(screen.queryByTestId("quiz-schedule")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Start evaluation" }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Delete quiz" })).toBeTruthy();
  });
});

describe("quiz page banner", () => {
  it("mirrors Schedule and Extend time next to Pause evaluation", async () => {
    state.routes.push({
      match: /\/quizzes\/q-live$/,
      body: {
        ...base,
        id: "q-live",
        title: "Week 9",
        status: "published",
        taking_open: true,
        taking_epoch: 1,
        exemption_count: 1,
        scheduled_end_at: "2026-11-12T03:00:00.000Z",
        settings: {},
        items: [],
      },
    });
    render(<QuizEditor quizId="q-live" />);
    expect(
      await screen.findByRole("button", { name: "Pause evaluation" }),
    ).toBeTruthy();
    expect(screen.getByTestId("quiz-schedule")).toBeTruthy();
    expect(screen.getByTestId("quiz-extend")).toBeTruthy();
    expect(screen.getByTestId("quiz-extended-badge")).toBeTruthy();
    expect(screen.getByText("Closes Nov 12, 11:00")).toBeTruthy();
  });
});

describe("student list V1 stickers", () => {
  it("keeps Start and shows Extended until when can_take_now is true", async () => {
    const api = {
      listCourseQuizzes: vi.fn(async () => [
        {
          ...base,
          id: "q-ext",
          group_id: null,
          title: "Week 8",
          status: "published" as const,
          attempt_count: 0,
          taking_open: false,
          taking_epoch: 2,
          can_take_now: true,
          exempt_until: "2026-11-12T10:00:00.000Z",
          published_at: "2026-11-01T00:00:00Z",
        },
      ]),
      listMyRecordAttempts: vi.fn(async () => []),
    };
    render(
      <StudentQuizList courseId="course-1" onStart={() => {}} api={api} />,
    );
    expect(await screen.findByText("Week 8")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start" })).toBeTruthy();
    expect(screen.getByTestId("quiz-extended-badge").textContent).toContain(
      "Extended until Nov 12, 18:00 UTC+8",
    );
    expect(screen.queryByTestId("quiz-not-open")).toBeNull();
  });

  it("shows Opens on a closed quiz that is not yet takeable", async () => {
    const api = {
      listCourseQuizzes: vi.fn(async () => [
        {
          ...base,
          id: "q-soon",
          group_id: null,
          title: "Week 12",
          status: "published" as const,
          attempt_count: 0,
          taking_open: false,
          taking_epoch: 0,
          can_take_now: false,
          scheduled_start_at: "2026-11-12T01:00:00.000Z",
          published_at: "2026-11-01T00:00:00Z",
        },
      ]),
      listMyRecordAttempts: vi.fn(async () => []),
    };
    render(
      <StudentQuizList courseId="course-1" onStart={() => {}} api={api} />,
    );
    expect(await screen.findByTestId("quiz-not-open")).toBeTruthy();
    expect(screen.getByText("Opens Nov 12, 09:00 UTC+8")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Start" })).toBeNull();
  });
});
