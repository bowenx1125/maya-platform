import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const state = vi.hoisted(() => ({
  api: {} as Record<string, ReturnType<typeof vi.fn>>,
  user: {
    id: "teacher-user",
    courses: [] as { course_id: string; role: "teacher" | "student" }[],
    groups: [] as { group_id: string; role: string }[],
  },
  pathname: "/student/knowledge",
  search: new URLSearchParams(),
  redirect: vi.fn(),
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
vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useSearchParams: () => state.search,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  redirect: state.redirect,
}));

import StudentGroupKnowledgePage from "../app/student/groups/[group_id]/knowledge/page";
import StudentKnowledgePage from "../app/student/knowledge/page";
import { AppShell } from "../components/app-shell";
import { GroupWorkspace } from "../components/student-workspace";

afterEach(() => {
  cleanup();
  state.api = {};
  state.user = {
    id: "teacher-user",
    courses: [],
    groups: [],
  };
  state.pathname = "/student/knowledge";
  state.search = new URLSearchParams();
  state.redirect.mockReset();
});

function setupActor(role: "teacher" | "student", includeJob = false) {
  state.user = {
    id: `${role}-user`,
    courses: [{ course_id: "course", role }],
    groups: [{ group_id: "joined-group", role: "member" }],
  };
  state.api = {
    group: vi.fn().mockResolvedValue({
      id: "joined-group",
      course_id: "course",
      name: "Joined group",
    }),
    courses: vi
      .fn()
      .mockResolvedValue([
        { id: "course", code: "MAYA-101", name: "Cultural exchange" },
      ]),
    knowledge: vi.fn().mockResolvedValue([]),
    workspaceDocuments: vi.fn().mockResolvedValue([]),
    brainformKnowledge: vi.fn().mockResolvedValue([]),
    chatAgents: vi.fn().mockResolvedValue([]),
    groups: vi
      .fn()
      .mockResolvedValue([
        { id: "joined-group", course_id: "course", name: "Joined group" },
      ]),
    teams: vi.fn().mockResolvedValue([]),
    mayaTeams: vi.fn().mockResolvedValue([]),
    courseAssessmentAttempts: vi.fn().mockResolvedValue([]),
    knowledgeGenerationJob: vi.fn().mockResolvedValue({
      job_id: "teacher-job",
      knowledge_set_id: "set-1",
      state: "succeeded",
    }),
  };
  // The page reads its query in the browser (useSearchParams).
  state.search = new URLSearchParams({
    group_id: "joined-group",
    course_id: "course",
    agent_id: "teacher-agent",
    set_id: "set-1",
    ...(includeJob ? { job_id: "teacher-job" } : {}),
  });
  return { page: <StudentKnowledgePage /> };
}

describe("legacy group Brainform actor context", () => {
  it("uses the joined Teacher course role and reads a Teacher-owned job", async () => {
    const { page } = setupActor("teacher", true);
    render(<>{await page}</>);

    await waitFor(() =>
      expect(state.api.brainformKnowledge).toHaveBeenCalledWith("course"),
    );
    expect(state.api.groups).toHaveBeenCalledWith("course");
    expect(state.api.knowledge).toHaveBeenCalledWith("joined-group");
    await waitFor(() =>
      expect(state.api.knowledgeGenerationJob).toHaveBeenCalledWith(
        "teacher-job",
      ),
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not give an actual Student access to a Teacher-owned job query", async () => {
    const { page } = setupActor("student", true);
    render(<>{await page}</>);

    await waitFor(() =>
      expect(state.api.brainformKnowledge).toHaveBeenCalledWith("course"),
    );
    expect(state.api.knowledgeGenerationJob).not.toHaveBeenCalled();
    expect(state.api.workspaceDocuments).not.toHaveBeenCalled();
  });

  it("keeps a visiting Teacher's joined-group Agents page read-only", async () => {
    state.pathname = "/student/agents";
    state.user = {
      id: "teacher-user",
      courses: [{ course_id: "course", role: "teacher" }],
      groups: [{ group_id: "joined-group", role: "member" }],
    };
    state.api = {
      group: vi.fn().mockResolvedValue({
        id: "joined-group",
        course_id: "course",
        name: "Joined group",
      }),
      agents: vi.fn().mockResolvedValue([]),
      versions: vi.fn().mockResolvedValue([]),
      chatAgents: vi.fn().mockResolvedValue([]),
      teams: vi.fn().mockResolvedValue([]),
    };
    render(
      <>
        <AppShell role="student">
          <GroupWorkspace groupId="joined-group" view="agents" />
        </AppShell>
      </>,
    );

    await screen.findByRole("heading", { name: "Agents" });
    expect(screen.queryByRole("link", { name: "New" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Voices" })).toBeNull();
    expect(
      screen.getByRole("link", { name: "Back" }).getAttribute("href"),
    ).toBe("/teacher/roster");
  });

  it("preserves group, course, Agent, Set, Job and mode on the legacy redirect", async () => {
    await StudentGroupKnowledgePage({
      params: Promise.resolve({ group_id: "joined-group" }),
      searchParams: Promise.resolve({
        course_id: "course",
        agent_id: "teacher-agent",
        set_id: "set-1",
        job_id: "teacher-job",
        mode: "knowledge-edit",
        document_id: "document-1",
      }),
    });

    const destination = state.redirect.mock.calls[0]?.[0] as string;
    const query = new URLSearchParams(destination.split("?", 2)[1]);
    expect(destination.split("?", 1)[0]).toBe("/student/knowledge");
    expect(Object.fromEntries(query)).toEqual({
      group_id: "joined-group",
      course_id: "course",
      agent_id: "teacher-agent",
      set_id: "set-1",
      job_id: "teacher-job",
      mode: "knowledge-edit",
      document_id: "document-1",
    });
  });
});
