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
  it("shows score min, score max, and rules only when AI grading is on", () => {
    render(<QuizEditor />);
    fireEvent.click(screen.getByRole("button", { name: /Short text/ }));

    expect(screen.getByRole("checkbox", { name: "AI grading" })).toBeTruthy();
    expect(screen.queryByRole("spinbutton", { name: "Score min" })).toBeNull();
    expect(screen.queryByRole("spinbutton", { name: "Score max" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Rules" })).toBeNull();
    expect(screen.getByText("Grading rubric")).toBeTruthy();

    fireEvent.click(screen.getByRole("checkbox", { name: "AI grading" }));
    expect(screen.getByRole("spinbutton", { name: "Score min" })).toBeTruthy();
    expect(screen.getByRole("spinbutton", { name: "Score max" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Rules" })).toBeTruthy();

    fireEvent.click(screen.getByRole("checkbox", { name: "AI grading" }));
    expect(screen.queryByRole("spinbutton", { name: "Score min" })).toBeNull();
    expect(screen.queryByRole("spinbutton", { name: "Score max" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Rules" })).toBeNull();
  });
});
