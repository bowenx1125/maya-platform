import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => {
  const defined: Record<string, unknown> = {
    group: async () => ({
      id: "group-a",
      course_id: "course-1",
      name: "Group A",
      members: [],
    }),
  };
  // Every other read answers an empty list, so the home renders its Guide.
  const api = new Proxy(defined, {
    get: (target, key: string) => target[key] ?? (async () => []),
  });
  return {
    api,
    user: {
      id: "student-a",
      display_name: "Learner",
      courses: [{ course_id: "course-1", role: "student" }],
      groups: [{ group_id: "group-a", role: "member" }],
    },
  };
});

vi.mock("next/navigation", () => ({
  usePathname: () => "/student",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    user: state.user,
    identityGeneration: 1,
    status: "authenticated",
    refresh: vi.fn(),
  }),
}));

import { StudentDashboard } from "../components/student-workspace";

afterEach(cleanup);

describe("student home Guide", () => {
  it("sends Add the RAG to the RAG create form, not the Knowledge page", async () => {
    render(<StudentDashboard />);
    const step = await screen.findByRole("link", { name: /Add the RAG/ });
    expect(step.getAttribute("href")).toBe(
      "/student/rag?group_id=group-a&mode=rag-new",
    );
  });
});
