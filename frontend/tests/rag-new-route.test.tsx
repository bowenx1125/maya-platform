import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const state = vi.hoisted(() => {
  const defined: Record<string, unknown> = {
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

afterEach(cleanup);

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
