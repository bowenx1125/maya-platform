import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  pathname: "/student",
  identityGeneration: 0,
  user: {
    id: "user-a",
    display_name: "Learner",
    courses: [] as { course_id: string; role: string }[],
    groups: [{ group_id: "group-a" }, { group_id: "group-b" }],
  },
  api: { agent: vi.fn(), version: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({ ...state, logout: vi.fn() }),
}));

import { AppShell } from "../components/app-shell";
import { LocaleProvider } from "../components/locale";

const content = () => (
  <LocaleProvider initialLocale="en">
    <AppShell role="student">
      <p>Content</p>
    </AppShell>
  </LocaleProvider>
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
    expect(links()).toContain("/student/groups/group-b");
    expect(links()).not.toContain("/student/groups/group-a");
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
    await waitFor(() => expect(links()).toContain("/student/groups/group-b"));
    await act(async () => resolveOld({ group_id: "group-a" }));
    expect(links()).not.toContain("/student/groups/group-a");
  });

  it("keeps teacher identity inside a visited group and offers the way back to Accounts", () => {
    state.pathname = "/student/groups/group-b";
    state.user.courses = [{ course_id: "course", role: "teacher" }];
    render(content());
    expect(
      screen.getByRole("link", { name: "Mayaform" }).getAttribute("href"),
    ).toBe("/teacher");
    expect(
      screen.getByRole("link", { name: "Studyform" }).getAttribute("href"),
    ).toBe("/teacher/studyform");
    expect(links()).toContain("/teacher/knowledge");
    expect(links()).toContain("/teacher/chat");
    expect(
      screen.getByRole("link", { name: "Accounts" }).getAttribute("href"),
    ).toBe("/teacher/roster");
    expect(
      screen.getByRole("link", { name: "Back" }).getAttribute("href"),
    ).toBe("/teacher/roster");
  });
});
