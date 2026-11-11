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
import { QuizApi, type QuizSummaryDTO } from "../lib/api/quiz";
import { QuizEditor } from "../components/quizzes/quiz-editor";
import { QuizzesList } from "../components/quizzes/quizzes-list";
import { QuizAttemptDetailView } from "../components/quiz/quiz-attempt-detail";
import { StudentQuizList } from "../components/quiz/quiz-list";
import { QuizTake } from "../components/quiz/quiz-take";

const state = vi.hoisted(() => ({ api: {} as PlatformApi }));
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
  usePathname: () => "/teacher/quizzes/quiz-1",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("../lib/confetti", () => ({ celebrate: vi.fn() }));

const quiz: QuizSummaryDTO = {
  id: "quiz-1",
  course_id: "course-1",
  title: "Week 3 Quiz",
  status: "published",
  schema_version: 1,
  content_revision: 1,
  created_by_user_id: "teacher-1",
  created_at: "",
  updated_at: "",
  taking_open: true,
  taking_epoch: 1,
  attempt_count: 1,
  show_results: false,
};
const attempt = {
  source: "quiz",
  attempt_id: "attempt-1",
  user_id: "student-1",
  student_name: "Ada",
  title: quiz.title,
  status: "submitted",
  submitted_at: "2026-11-10T09:00:00Z",
  score_objective: 3,
  score_max_objective: 4,
  grading_status: "complete",
  quiz_id: quiz.id,
  points_awarded: 4,
  points_total: 5,
  taking_epoch: 1,
};
const items = [
  {
    id: "q1",
    type: "single",
    prompt: "Which layer handles auth?",
    choices: [{ id: "a", label: "API gateway" }],
    points: 4,
    response_choice_ids: ["a"],
    correct: true,
    points_awarded: 4,
    graded: true,
  },
  {
    id: "q-wrong",
    type: "multiple",
    prompt: "Choose an input.",
    choices: [{ id: "b", label: "Oxygen" }],
    points: 1,
    response_choice_ids: ["b"],
    correct: false,
    points_awarded: 0,
    graded: true,
  },
  {
    id: "q2",
    type: "short_text",
    prompt: "Why use a queue?",
    choices: [],
    points: 1,
    response_text: "Decouple producers",
    correct: null,
    points_awarded: 0,
    graded: true,
    feedback: "Name a second reason.",
  },
];

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  state.api = new PlatformApi({ csrfToken: "c".repeat(32) });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/my-record-attempts")) return json([]);
      if (url.endsWith("/quizzes")) return json([quiz]);
      return json({ ...quiz, settings: {}, items: [] });
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("teacher results visibility", () => {
  it.each([false, true])(
    "optimistically toggles from shown=%s, stays busy until saved, then reverts a failed change",
    async (initial) => {
      vi.mocked(fetch).mockResolvedValueOnce(
        json({ ...quiz, show_results: initial, settings: {}, items: [] }),
      );
      render(<QuizEditor quizId={quiz.id} />);
      const pill = await screen.findByRole("switch");
      expect(pill.getAttribute("data-testid")).toBe("quiz-results-toggle");
      expect(pill.getAttribute("aria-checked")).toBe(String(initial));
      expect(pill.textContent).toBe(
        initial ? "Results shown" : "Results hidden",
      );
      expect(pill.className).toContain(initial ? "bg-[#BEF264]" : "bg-white");
      expect(
        pill.querySelector('[aria-hidden="true"] > span')?.parentElement
          ?.className,
      ).toContain(initial ? "justify-end" : "justify-start");
      const originalIcon = pill.querySelector("path")?.getAttribute("d");
      expect(pill.closest("[data-ui-guide]")).toBeNull();
      expect(screen.queryByText("?")).toBeNull();
      expect(screen.queryByRole("tooltip")).toBeNull();
      expect(
        screen.getAllByText(initial ? "Results shown" : "Results hidden"),
      ).toHaveLength(1);
      const extend = screen.getByTestId("quiz-extend");
      const download = screen.getByTestId("quiz-export-download");
      expect(
        extend.compareDocumentPosition(pill) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(
        pill.compareDocumentPosition(download) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();

      let resolve!: (next: QuizSummaryDTO) => void;
      const save = vi
        .spyOn(QuizApi.prototype, "setResultsVisible")
        .mockImplementationOnce(
          () =>
            new Promise((done) => {
              resolve = done;
            }),
        );
      fireEvent.click(pill);
      expect(save).toHaveBeenCalledWith("course-1", quiz.id, !initial);
      expect(pill.getAttribute("aria-checked")).toBe(String(!initial));
      expect(pill.getAttribute("aria-busy")).toBe("true");
      expect((pill as HTMLButtonElement).disabled).toBe(true);
      expect(pill.className).toContain("aria-busy:animate-debate-fill");
      expect(pill.querySelector("path")?.getAttribute("d")).not.toBe(
        originalIcon,
      );
      fireEvent.click(pill);
      expect(save).toHaveBeenCalledTimes(1);
      resolve({ ...quiz, show_results: !initial });
      await waitFor(() => expect(pill.getAttribute("aria-busy")).toBeNull());
      expect(pill.getAttribute("aria-checked")).toBe(String(!initial));

      let reject!: (reason: Error) => void;
      save.mockImplementationOnce(
        () =>
          new Promise((_, fail) => {
            reject = fail;
          }),
      );
      fireEvent.click(pill);
      expect(pill.getAttribute("aria-checked")).toBe(String(initial));
      reject(new Error("Could not change results."));
      await waitFor(() => expect(pill.getAttribute("aria-busy")).toBeNull());
      expect(pill.getAttribute("aria-checked")).toBe(String(!initial));
      expect(screen.getByText("Could not change results.")).toBeTruthy();
    },
  );

  it.each([false, true])(
    "has only the row sticker when shown=%s",
    async (shown) => {
      vi.mocked(fetch).mockResolvedValueOnce(
        json([{ ...quiz, show_results: shown }]),
      );
      render(<QuizzesList />);
      const row = await screen.findByTestId("quiz-row");
      expect(screen.queryByRole("switch")).toBeNull();
      expect(screen.queryByTestId("quiz-results-toggle")).toBeNull();
      const sticker = within(row).queryByText("Results shown");
      expect(Boolean(sticker)).toBe(shown);
      if (sticker) {
        expect(sticker.className).toContain("bg-[#A5F3FC]");
        expect(sticker.querySelector("svg")).toBeTruthy();
      }
      expect(screen.queryByText("?")).toBeNull();
    },
  );

  it("sends the results PUT with the boolean and CSRF header", async () => {
    await new QuizApi(state.api).setResultsVisible("course-1", quiz.id, true);
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/courses/course-1/quizzes/quiz-1/results",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ show_results: true }),
        headers: expect.objectContaining({ "X-CSRF-Token": "c".repeat(32) }),
      }),
    );
  });
});

describe("student results visibility", () => {
  it.each([false, true, undefined])(
    "renders and expands an attempt when show_results=%s",
    async (shown) => {
      vi.stubGlobal(
        "fetch",
        vi.fn(async (input: RequestInfo | URL) => {
          const url = String(input);
          if (url.endsWith("/quizzes")) return json([]);
          if (url.endsWith("/my-record-attempts"))
            return json([{ ...attempt, show_results: shown }]);
          // Keep grades populated to prove visibility comes from the flag.
          return json({
            ...attempt,
            view: "student",
            show_results: shown,
            items,
          });
        }),
      );
      render(<StudentQuizList courseId="course-1" onStart={vi.fn()} />);
      const row = await screen.findByRole("button", { name: /Week 3 Quiz/ });
      expect(row.getAttribute("aria-expanded")).toBe("false");
      if (shown === false) {
        const sticker = within(row).getByText("Submitted");
        expect(sticker.className).toContain("bg-[#BEF264]");
        expect(sticker.className).toContain("-rotate-1");
        expect(sticker.querySelector("svg")).toBeTruthy();
        expect(row.textContent).not.toMatch(/Graded|Not graded|4 \/ 5/);
      } else {
        expect(within(row).getByText("Graded")).toBeTruthy();
        expect(row.textContent).toContain("4 / 5");
        expect(within(row).queryByText("Submitted")).toBeNull();
      }
      fireEvent.click(row);
      const sheet = await screen.findByTestId("quiz-attempt-detail");
      expect(row.getAttribute("aria-expanded")).toBe("true");
      expect(within(sheet).getByText("API gateway")).toBeTruthy();
      expect(within(sheet).getByText("Decouple producers")).toBeTruthy();
      expect(
        within(sheet).queryByRole("columnheader", { name: "Key" }),
      ).toBeNull();
      if (shown === false) {
        expect(
          within(sheet)
            .getAllByRole("columnheader")
            .map((cell) => cell.textContent),
        ).toEqual(["#", "Question", "Answer"]);
        expect(sheet.textContent).not.toMatch(
          /Correct|Incorrect|Points|Feedback|Graded|graded|4 \/ 5|Name a second reason/,
        );
        expect(sheet.querySelector('[aria-label="4 / 5"]')).toBeNull();
        for (const tr of within(sheet).getAllByRole("row")) {
          expect(tr.className).not.toMatch(/bg-/);
        }
      } else {
        expect(
          within(sheet).getByRole("columnheader", { name: "Points" }),
        ).toBeTruthy();
        expect(
          within(sheet).getByRole("columnheader", { name: "Feedback" }),
        ).toBeTruthy();
        expect(within(sheet).getByText("Correct")).toBeTruthy();
        expect(within(sheet).getByText("Incorrect")).toBeTruthy();
        expect(within(sheet).getByText("Name a second reason.")).toBeTruthy();
        expect(within(sheet).getByLabelText("4 / 5")).toBeTruthy();
      }
      expect(screen.queryByText("?")).toBeNull();
      expect(screen.queryByRole("tooltip")).toBeNull();
      fireEvent.click(row);
      expect(screen.queryByTestId("quiz-attempt-detail")).toBeNull();
    },
  );

  it("accepts fully redacted scores and grading in the student paper", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      json({
        ...attempt,
        view: "student",
        show_results: false,
        points_awarded: null,
        points_total: null,
        score_objective: null,
        score_max_objective: null,
        grading_status: null,
        items: items.map((item) => ({
          ...item,
          correct: null,
          points_awarded: null,
          feedback: null,
          graded: false,
        })),
      }),
    );
    render(
      <QuizAttemptDetailView
        courseId="course-1"
        quizId={quiz.id}
        attemptId="attempt-1"
        teacher={false}
      />,
    );
    const sheet = await screen.findByTestId("quiz-attempt-detail");
    expect(within(sheet).getByText("Decouple producers")).toBeTruthy();
    expect(sheet.textContent).not.toMatch(
      /Correct|Incorrect|Points|Feedback|graded|NaN|null/,
    );
  });

  it.each([
    { shown: false, redacted: false },
    { shown: false, redacted: true },
    { shown: true, redacted: false },
    { shown: undefined, redacted: false },
  ])(
    "uses the fetched quiz flag after submission: %j",
    async ({ shown, redacted }) => {
      vi.stubGlobal(
        "fetch",
        vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
          json(
            init?.method === "POST"
              ? {
                  ...attempt,
                  id: "attempt-1",
                  ...(redacted
                    ? {
                        score_objective: null,
                        score_max_objective: null,
                        grading_status: null,
                      }
                    : {}),
                }
              : { ...quiz, show_results: shown, settings: {}, items },
          ),
        ),
      );
      render(
        <QuizTake courseId="course-1" quizId={quiz.id} onExit={vi.fn()} />,
      );
      fireEvent.click(await screen.findByText("API gateway"));
      fireEvent.click(screen.getByRole("button", { name: "Submit" }));
      expect(await screen.findByText("Submitted")).toBeTruthy();
      if (shown === false) {
        expect(screen.getByText("Your answers are in.")).toBeTruthy();
        expect(screen.queryByText(/Objective score/)).toBeNull();
      } else {
        expect(screen.getByText("Objective score: 3 / 4 (75%)")).toBeTruthy();
      }
      expect(screen.queryByText("?")).toBeNull();
    },
  );
});
