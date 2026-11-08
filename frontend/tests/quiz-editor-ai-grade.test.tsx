import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: { getCsrfToken: () => "c".repeat(32) },
    user: {
      id: "user-1",
      courses: [{ course_id: "course-1", role: "teacher" }],
      groups: [],
    },
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import QuizEditor from "../components/quizzes/quiz-editor";

afterEach(() => {
  cleanup();
});

describe("quiz editor AI grading", () => {
  it("is one switch beside Required on text questions; the rubric is what AI grades by", () => {
    render(<QuizEditor />);
    fireEvent.click(screen.getByRole("button", { name: /Single choice/ }));
    expect(screen.queryByRole("checkbox", { name: "AI grading" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Short text/ }));
    const toggle = screen.getByRole("checkbox", { name: "AI grading" });
    expect((toggle as HTMLInputElement).checked).toBe(false);
    fireEvent.click(toggle);
    expect((toggle as HTMLInputElement).checked).toBe(true);
    // No second rules box and no range to fill in.
    expect(screen.queryByRole("spinbutton", { name: "Score min" })).toBeNull();
    expect(screen.queryByRole("spinbutton", { name: "Score max" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Rules" })).toBeNull();
    expect(screen.getAllByText("Grading rubric")).toHaveLength(1);
  });

  it("says why Done is blocked in plain words", () => {
    render(<QuizEditor />);
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Week 12" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Short text/ }));
    fireEvent.change(screen.getByLabelText("Prompt"), {
      target: { value: "Why does Raft need a leader?" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "AI grading" }));
    fireEvent.change(screen.getByLabelText("Grading rubric"), {
      target: { value: "Short" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(
      screen.getByText(
        "AI grading needs a grading rubric of at least 20 characters.",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText("The platform request could not be completed."),
    ).toBeNull();
  });
});
