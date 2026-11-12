import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { invalidateRequestCache } from "../lib/request-cache";

const state = vi.hoisted(() => {
  const defined: Record<string, unknown> = {
    chatAgents: vi.fn(async (_courseId: string) => []),
    group: async () => ({
      id: "group-a",
      course_id: "course-1",
      name: "Group A",
    }),
    groups: async () => [
      { id: "group-a", course_id: "course-1", name: "Group A" },
    ],
    courses: async () => [
      { id: "course-1", code: "MAYA-101", name: "Cultural exchange" },
      { id: "course-2", code: "MAYA-102", name: "Maya1002" },
    ],
  };
  const api = new Proxy(defined, {
    get: (target, key: string) => target[key] ?? (async () => []),
  });
  return {
    api,
    search: new URLSearchParams(),
    user: {
      id: "student-a",
      username: "student-a",
      display_name: "Learner",
      courses: [{ course_id: "course-1", role: "student" }],
      groups: [{ group_id: "group-a", role: "member" }],
    },
  };
});

vi.mock("next/navigation", () => ({
  usePathname: () => "/student/rag",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => state.search,
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    user: state.user,
    identityGeneration: 1,
    status: "authenticated",
    logout: vi.fn(),
  }),
  RouteGuard: ({ children }: { children: ReactNode }) => children,
}));

import StudentRagPage from "../app/student/rag/page";
import StudentKnowledgePage from "../app/student/knowledge/page";
import TeacherRagPage from "../app/teacher/rag/page";
import TeacherKnowledgePage from "../app/teacher/knowledge/page";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  invalidateRequestCache(state.api);
  state.search = new URLSearchParams();
  state.user.username = "student-a";
  state.user.courses = [{ course_id: "course-1", role: "student" }];
});

describe.each([
  ["RAG", StudentRagPage, TeacherRagPage],
  ["Knowledge", StudentKnowledgePage, TeacherKnowledgePage],
])("%s course scope", (_name, StudentPage, TeacherPage) => {
  it.each(["course-1", "course-2"])(
    "keeps Bowen in login class %s without a course picker",
    async (selectedCourse) => {
      state.user.username = "bowen";
      const otherCourse =
        selectedCourse === "course-1" ? "course-2" : "course-1";
      state.user.courses = [selectedCourse, otherCourse].map((course_id) => ({
        course_id,
        role: "student",
      }));
      // A stale page link must not replace the class selected at login.
      state.search = new URLSearchParams({ course_id: otherCourse });
      const { rerender } = render(<StudentPage />);
      await waitFor(() =>
        expect(state.api.chatAgents).toHaveBeenCalledWith(selectedCourse),
      );
      expect(state.api.chatAgents).not.toHaveBeenCalledWith(otherCourse);
      expect(screen.queryByRole("combobox", { name: "Course" })).toBeNull();

      // Auth refresh/re-entry can change the first class on the same page.
      state.user.courses = [...state.user.courses].reverse();
      rerender(<StudentPage />);
      await waitFor(() =>
        expect(state.api.chatAgents).toHaveBeenCalledWith(otherCourse),
      );
      expect(screen.queryByRole("combobox", { name: "Course" })).toBeNull();
    },
  );

  it("keeps the normal single-class student view", async () => {
    render(<StudentPage />);
    await waitFor(() =>
      expect(state.api.chatAgents).toHaveBeenCalledWith("course-1"),
    );
    expect(screen.queryByRole("combobox", { name: "Course" })).toBeNull();
  });

  it("preserves Bowen's explicitly authorized group link", async () => {
    state.user.username = "bowen";
    state.user.courses = ["course-2", "course-1"].map((course_id) => ({
      course_id,
      role: "student",
    }));
    state.search = new URLSearchParams({ group_id: "group-a" });
    render(<StudentPage />);
    await waitFor(() =>
      expect(state.api.chatAgents).toHaveBeenCalledWith("course-1"),
    );
    expect(screen.queryByRole("combobox", { name: "Course" })).toBeNull();
  });

  it("preserves an ordinary multi-class student's course picker", async () => {
    state.user.courses.push({ course_id: "course-2", role: "student" });
    render(<StudentPage />);
    const picker = await screen.findByRole("combobox", { name: "Course" });
    await screen.findByRole("option", { name: "Maya1002" });
    fireEvent.change(picker, { target: { value: "course-2" } });
    await waitFor(() =>
      expect(state.api.chatAgents).toHaveBeenCalledWith("course-2"),
    );
  });

  it("keeps the teacher's active class without a student course picker", async () => {
    state.user.username = "maya";
    state.user.courses = ["course-2", "course-1"].map((course_id) => ({
      course_id,
      role: "teacher",
    }));
    state.search = new URLSearchParams({ course_id: "course-1" });
    render(<TeacherPage />);
    await waitFor(() =>
      expect(state.api.chatAgents).toHaveBeenCalledWith("course-2"),
    );
    expect(state.api.chatAgents).not.toHaveBeenCalledWith("course-1");
    expect(screen.queryByRole("combobox", { name: "Course" })).toBeNull();
  });
});

describe("RAG page ?mode=rag-new (the Guide's Add the RAG)", () => {
  it("opens the RAG create form", async () => {
    state.search = new URLSearchParams({
      group_id: "group-a",
      mode: "rag-new",
    });
    render(<StudentRagPage />);
    expect(await screen.findByText("File Name")).toBeTruthy();
  });

  it("stays on the RAG list without it", async () => {
    state.search = new URLSearchParams({ group_id: "group-a" });
    render(<StudentRagPage />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "RAG" })).toBeTruthy(),
    );
    expect(screen.queryByText("File Name")).toBeNull();
  });
});
