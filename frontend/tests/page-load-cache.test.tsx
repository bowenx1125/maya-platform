import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  session: {
    api: {} as Record<string, ReturnType<typeof vi.fn>>,
    identityGeneration: 1,
    user: null as unknown,
  },
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => h.session,
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/student/groups/group-1",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { BrainformWorkspace } from "../components/knowledge/brainform-workspace";
import { GroupWorkspace } from "../components/student-workspace";
import { PlatformApiError } from "../lib/api/platform";
import { FRESH_MS } from "../lib/request-cache";

const team = (name: string) => ({
  id: `team-${name}`,
  display_name: name,
  current_version_seq: 1,
  visibility: "public",
  can_edit: false,
});

function signIn(userId = "student-a") {
  const api = {
    group: vi.fn().mockResolvedValue({
      id: "group-1",
      course_id: "course-1",
      name: "Group One",
    }),
    agents: vi.fn().mockResolvedValue([]),
    versions: vi.fn().mockResolvedValue([]),
    teams: vi.fn().mockResolvedValue([team("First Team")]),
    chatAgents: vi.fn().mockResolvedValue([]),
    publishedAgents: vi.fn().mockResolvedValue([]),
    voiceProfiles: vi.fn().mockResolvedValue([]),
    deleteTeam: vi.fn().mockResolvedValue(undefined),
    // Studyform also holds Brainform's RAG and Record cards.
    courses: vi.fn().mockResolvedValue([{ id: "course-1", name: "Course" }]),
    knowledge: vi.fn().mockResolvedValue([]),
    brainformKnowledge: vi.fn().mockResolvedValue([]),
    myAssessmentAttempts: vi.fn().mockResolvedValue([]),
  };
  h.session = {
    api,
    identityGeneration: 1,
    user: {
      id: userId,
      courses: [{ course_id: "course-1", role: "student" }],
      groups: [{ group_id: "group-1", role: "member" }],
    },
  };
  return api;
}

function show() {
  return render(
    <>
      <GroupWorkspace groupId="group-1" />
    </>,
  );
}

function laterVisit() {
  const now = Date.now() + FRESH_MS + 1_000;
  vi.spyOn(Date, "now").mockReturnValue(now);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Studyform page cache", () => {
  it("paints the last page at once on a later visit and replaces it with the refresh", async () => {
    const api = signIn("student-paint");
    const first = show();
    expect(await screen.findByText("First Team")).toBeTruthy();
    first.unmount();
    laterVisit();
    api.teams.mockResolvedValue([team("Second Team")]);
    show();
    // From the snapshot, in the first render: no loading card.
    expect(screen.getByText("First Team")).toBeTruthy();
    expect(await screen.findByText("Second Team")).toBeTruthy();
  });

  it("drops the painted page when the refresh is refused", async () => {
    const api = signIn("student-refused");
    const first = show();
    expect(await screen.findByText("First Team")).toBeTruthy();
    first.unmount();
    laterVisit();
    api.group.mockRejectedValue(
      new PlatformApiError(404, "Group not found.", { code: "not_found" }),
    );
    show();
    await waitFor(() => expect(screen.queryByText("First Team")).toBeNull());
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("keeps the painted page when the server is busy", async () => {
    const api = signIn("student-busy");
    const first = show();
    expect(await screen.findByText("First Team")).toBeTruthy();
    first.unmount();
    laterVisit();
    api.teams.mockRejectedValue(
      new PlatformApiError(503, "busy", { code: "server_busy" }),
    );
    show();
    await waitFor(() => expect(api.teams).toHaveBeenCalledTimes(2));
    await new Promise((done) => setTimeout(done, 20));
    expect(screen.getByText("First Team")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("never paints another identity's page", async () => {
    signIn("student-one");
    const first = show();
    expect(await screen.findByText("First Team")).toBeTruthy();
    first.unmount();
    const api = signIn("student-two");
    api.teams.mockResolvedValue([team("Own Team")]);
    show();
    expect(screen.queryByText("First Team")).toBeNull();
    expect(await screen.findByText("Own Team")).toBeTruthy();
  });

  it("re-reads after deleting a Team instead of reusing the cached page", async () => {
    const api = signIn("student-delete");
    api.teams.mockResolvedValue([{ ...team("Mine"), can_edit: true }]);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const first = show();
    expect(await screen.findByText("Mine")).toBeTruthy();
    (await screen.findByRole("button", { name: /Delete/ })).click();
    await waitFor(() => expect(screen.queryByText("Mine")).toBeNull());
    first.unmount();
    api.teams.mockResolvedValue([]);
    show();
    expect(screen.queryByText("Mine")).toBeNull();
    await waitFor(() => expect(api.teams).toHaveBeenCalledTimes(2));
  });

  it("Brainform hides painted lists when the refresh is refused", async () => {
    // Only teachers see the Knowledge card now (2026-10-20).
    const api: Record<string, ReturnType<typeof vi.fn>> = signIn(
      "teacher-brainform",
    );
    (h.session.user as { courses: unknown[] }).courses = [
      { course_id: "course-1", role: "teacher" },
    ];
    Object.assign(api, {
      courses: vi.fn().mockResolvedValue([{ id: "course-1", name: "Course" }]),
      groups: vi.fn().mockResolvedValue([]),
      knowledge: vi.fn().mockResolvedValue([]),
      workspaceDocuments: vi.fn().mockResolvedValue([]),
      mayaTeams: vi.fn().mockResolvedValue([]),
      brainformKnowledge: vi.fn().mockResolvedValue([
        {
          canonical_set_id: "set-1",
          source_agent_display_name: "Socrates",
          knowledge_display_name: "Socrates Knowledge",
          version_seq: 1,
          content_hash: "b".repeat(64),
          projection_available: true,
          can_read: true,
          can_edit: false,
          created_at: "2026-10-06T00:00:00Z",
        },
      ]),
    });
    const page = () => (
      <>
        <BrainformWorkspace role="teacher" />
      </>
    );
    const first = render(page());
    expect(await screen.findByText("Socrates Knowledge")).toBeTruthy();
    first.unmount();
    laterVisit();
    api.brainformKnowledge.mockRejectedValue(
      new PlatformApiError(403, "Forbidden", { code: "forbidden" }),
    );
    render(page());
    expect(screen.getByText("Socrates Knowledge")).toBeTruthy();
    await waitFor(() =>
      expect(screen.queryByText("Socrates Knowledge")).toBeNull(),
    );
  });
});
