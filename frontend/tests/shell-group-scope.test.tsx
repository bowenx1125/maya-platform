import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  pathname: "/student",
  push: vi.fn(),
  identityGeneration: 0,
  user: {
    id: "user-a",
    display_name: "Learner",
    courses: [] as { course_id: string; role: string }[],
    groups: [{ group_id: "group-a" }, { group_id: "group-b" }],
  },
  api: {
    agent: vi.fn(),
    version: vi.fn(),
    leaveGroupAsTeacher: undefined as ReturnType<typeof vi.fn> | undefined,
  } as {
    agent: ReturnType<typeof vi.fn>;
    version: ReturnType<typeof vi.fn>;
    leaveGroupAsTeacher: ReturnType<typeof vi.fn> | undefined;
    joinGroupAsTeacher?: ReturnType<typeof vi.fn>;
  },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useRouter: () => ({ replace: vi.fn(), push: state.push }),
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({ ...state, logout: vi.fn() }),
}));

import { AppShell } from "../components/app-shell";
import { PlatformApiError } from "../lib/api/platform";
import { forgetVisitRenewal, VISIT_RENEW_MS } from "../lib/teacher-visit";

const content = () => (
  <>
    <AppShell role="student">
      <p>Content</p>
    </AppShell>
  </>
);
const links = () =>
  screen.getAllByRole("link").map((link) => link.getAttribute("href"));

beforeEach(() => {
  state.user.id = "user-a";
  state.user.courses = [];
  state.identityGeneration = 0;
  vi.resetAllMocks();
});
afterEach(cleanup);

describe("group navigation scope", () => {
  it("follows the group on screen rather than the first membership", () => {
    state.pathname = "/student/groups/group-b/knowledge";
    render(content());
    expect(links()).toContain("/student/agents?group_id=group-b");
    expect(links()).not.toContain("/student/agents?group_id=group-a");
    expect(screen.queryByRole("button", { name: "Backout" })).toBeNull();
    expect(screen.getByRole("button", { name: "Logout" })).toBeTruthy();
    expect(state.api.agent).not.toHaveBeenCalled();
  });

  it("ignores an old identity's late Agent group lookup", async () => {
    state.pathname = "/student/agents/agent-id";
    let resolveOld!: (value: { group_id: string }) => void;
    state.api.agent
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveOld = resolve;
          }),
      )
      .mockResolvedValueOnce({ group_id: "group-b" });
    const view = render(content());
    await waitFor(() => expect(state.api.agent).toHaveBeenCalledTimes(1));
    state.user = { ...state.user, id: "user-b" };
    state.identityGeneration = 1;
    view.rerender(content());
    await waitFor(() =>
      expect(links()).toContain("/student/agents?group_id=group-b"),
    );
    await act(async () => resolveOld({ group_id: "group-a" }));
    expect(links()).not.toContain("/student/agents?group_id=group-a");
  });

  it("keeps teacher identity inside a visited group and offers the way back to Accounts", async () => {
    state.pathname = "/student/groups/group-b";
    state.user.courses = [{ course_id: "course", role: "teacher" }];
    const leave = vi.fn(async () => undefined);
    state.api = {
      agent: vi.fn(),
      version: vi.fn(),
      leaveGroupAsTeacher: leave,
    };
    render(content());
    expect(
      screen.getByRole("link", { name: "Mayaform" }).getAttribute("href"),
    ).toBe("/teacher");
    // Studyform, Brainform and Chatform stay in the visited group.
    expect(
      screen.getByRole("link", { name: "Agents" }).getAttribute("href"),
    ).toBe("/student/agents?group_id=group-b");
    // The visit shows what the group's members see: their RAG, no Knowledge.
    expect(links()).toContain("/teacher/rag?group_id=group-b");
    expect(links().some((href) => href?.startsWith("/teacher/knowledge"))).toBe(
      false,
    );
    expect(screen.queryByRole("link", { name: "Knowledge" })).toBeNull();
    expect(links()).toContain("/teacher/chat?group_id=group-b");
    expect(
      screen.getByRole("link", { name: "Accounts" }).getAttribute("href"),
    ).toBe("/teacher/roster");
    expect(screen.queryByRole("link", { name: "Back" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Backward" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Logout" })).toBeNull();
    const backout = screen.getByRole("button", { name: "Backout" });
    const mail = screen.getByRole("link", { name: /Send to/ });
    expect(
      mail.compareDocumentPosition(backout) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.click(backout);
    await waitFor(() => expect(leave).toHaveBeenCalledWith("group-b"));
    expect(leave).toHaveBeenCalledWith("group-a");
    expect(state.push).toHaveBeenCalledWith("/teacher/roster");
  });
});

describe("a teacher's visit to a group", () => {
  beforeEach(() => {
    state.pathname = "/student/groups/group-b";
    state.user.courses = [{ course_id: "course", role: "teacher" }];
    forgetVisitRenewal("group-b");
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renews the visit while the teacher stays, so a long lesson is not cut off", async () => {
    vi.useFakeTimers();
    const join = vi.fn(async () => ({}));
    state.api = {
      agent: vi.fn(),
      version: vi.fn(),
      leaveGroupAsTeacher: vi.fn(async () => undefined),
      joinGroupAsTeacher: join,
    };
    render(content());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(join).toHaveBeenCalledTimes(1);
    expect(join).toHaveBeenCalledWith("group-b");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(VISIT_RENEW_MS - 60_000);
    });
    expect(join).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(join).toHaveBeenCalledTimes(2);
    // 2 h 30 min later the teacher is still inside, renewed all along.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(130 * 60_000);
    });
    expect(join.mock.calls.length).toBeGreaterThanOrEqual(8);
    expect(screen.queryByText("Your visit to this group has ended")).toBeNull();
  });

  it("says plainly when the visit has ended and offers the way back to Accounts", async () => {
    state.api = {
      agent: vi.fn(),
      version: vi.fn(),
      leaveGroupAsTeacher: vi.fn(async () => undefined),
      joinGroupAsTeacher: vi.fn(async () => {
        throw new PlatformApiError(403, "forbidden", { code: "forbidden" });
      }),
    };
    render(content());
    expect(
      await screen.findByText("Your visit to this group has ended"),
    ).toBeTruthy();
    const back = screen.getByRole("link", { name: "Back to Accounts" });
    expect(back.getAttribute("href")).toBe("/teacher/roster");
  });
});
