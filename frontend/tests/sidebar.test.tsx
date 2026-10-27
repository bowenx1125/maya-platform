/**
 * Sidebar (DESIGN-RULES §7, proposals/09-sidebar): groups by role, collapse
 * (C) with the edge toggle (A), Ctrl/⌘+B, persistence and the Live states.
 */
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  pathname: "/student",
  identityGeneration: 0,
  user: {
    id: "user-a",
    display_name: "Learner",
    courses: [{ course_id: "course-1", role: "student" }],
    groups: [{ group_id: "group-a", role: "member" }] as {
      group_id: string;
      role: string;
    }[],
  },
  api: { classroomLive: vi.fn(), agent: vi.fn(), version: vi.fn() },
  refresh: vi.fn(async () => null),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({ ...state, logout: vi.fn() }),
}));

import { AppShell, SIDEBAR_COLLAPSED_KEY } from "../components/app-shell";

const student = () => ({
  id: "user-a",
  display_name: "Learner",
  courses: [{ course_id: "course-1", role: "student" }],
  groups: [{ group_id: "group-a", role: "member" }],
});
const teacher = () => ({
  id: "user-t",
  display_name: "Teacher",
  courses: [{ course_id: "course-1", role: "teacher" }],
  groups: [] as { group_id: string; role: string }[],
});

function renderShell(role: "student" | "teacher", pathname: string) {
  state.pathname = pathname;
  return render(
    <AppShell role={role}>
      <p>content</p>
    </AppShell>,
  );
}

const nav = () => within(screen.getByRole("navigation"));
function groupRows(name: string) {
  const group = screen
    .getAllByRole("group")
    .find(
      (element) =>
        element.getAttribute("aria-label") === name ||
        element.querySelector(`#${element.getAttribute("aria-labelledby")}`)
          ?.textContent === name,
    );
  if (!group) throw new Error(`no group ${name}`);
  return [...group.querySelectorAll("li")].map((row) =>
    (
      row.firstElementChild?.getAttribute("aria-label") ??
      row.firstElementChild?.textContent ??
      ""
    ).trim(),
  );
}
const toggle = () =>
  screen
    .getAllByRole("button", { name: /sidebar$/ })
    .find((button) => button.hasAttribute("aria-keyshortcuts"))!;

beforeEach(() => {
  window.localStorage.clear();
  state.user = student();
  state.api.classroomLive.mockReset().mockResolvedValue(null);
  vi.stubGlobal(
    "WebSocket",
    class {
      close() {}
    },
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("sidebar groups", () => {
  it("gives a student Studyform, Brainform, Chatform and Classroom (Live)", () => {
    renderShell("student", "/student");
    expect(groupRows("Studyform")).toEqual(["Agents", "Teams"]);
    expect(groupRows("Brainform")).toEqual(["RAG", "Voices", "Record"]);
    expect(groupRows("Chatform")).toEqual([
      "Chat with Agent",
      "Chat with Team",
    ]);
    expect(groupRows("Classroom")).toEqual(["Live"]);
    expect(
      nav().getByRole("link", { name: "Voices" }).getAttribute("href"),
    ).toBe("/student/voices?group_id=group-a");
    expect(
      nav().getByRole("link", { name: "Chat with Team" }).getAttribute("href"),
    ).toBe("/student/chat");
    // Brainform has no page of its own for a student: a heading, not a link,
    // and the Guide's Brainform step points at that heading.
    expect(
      document.querySelector('[data-tour="brain"]')?.textContent?.trim(),
    ).toBe("Brainform");
  });

  it("gives a teacher Knowledge in Brainform and Debates and Accounts in Classroom", () => {
    state.user = teacher();
    renderShell("teacher", "/teacher");
    expect(groupRows("Studyform")).toEqual(["Agents", "Teams"]);
    expect(groupRows("Brainform")).toEqual([
      "RAG",
      "Voices",
      "Record",
      "Knowledge",
    ]);
    expect(groupRows("Classroom")).toEqual(["Debates", "Accounts"]);
    expect(nav().queryByText("Live")).toBeNull();
    expect(
      nav().getByRole("link", { name: "Agents" }).getAttribute("href"),
    ).toBe("/teacher/agents");
    // RAG, Voices, Knowledge are their own split pages.
    expect(nav().getByRole("link", { name: "RAG" }).getAttribute("href")).toBe(
      "/teacher/rag",
    );
    expect(
      nav().getByRole("link", { name: "Voices" }).getAttribute("href"),
    ).toBe("/teacher/voices");
    expect(
      nav().getByRole("link", { name: "Knowledge" }).getAttribute("href"),
    ).toBe("/teacher/knowledge");
  });

  it("keeps a visiting teacher's Brainform entry for that group", () => {
    state.user = { ...teacher(), groups: [{ group_id: "g", role: "admin" }] };
    renderShell("teacher", "/student/groups/g");
    expect(nav().getByRole("link", { name: "RAG" }).getAttribute("href")).toBe(
      "/teacher/rag?group_id=g",
    );
    expect(
      nav().getByRole("link", { name: "Voices" }).getAttribute("href"),
    ).toBe("/teacher/voices?group_id=g");
    expect(
      nav().getByRole("link", { name: "Chat with Agent" }).getAttribute("href"),
    ).toBe("/teacher/chat?group_id=g");
  });

  it("lights only RAG (or Knowledge) for a teacher, never Teams", () => {
    state.user = teacher();
    const lit = () =>
      [...document.querySelectorAll("[data-lit]")].map((element) =>
        element.getAttribute("data-sidebar-item"),
      );
    const rag = renderShell("teacher", "/teacher/rag");
    expect(lit()).toEqual(["rag"]);
    rag.unmount();
    renderShell("teacher", "/teacher/knowledge");
    expect(lit()).toEqual(["knowledge"]);
  });

  it("lights one row: Voices on its page, else the first row for the page", () => {
    const view = renderShell("student", "/student/voices");
    const lit = () =>
      [...document.querySelectorAll("[data-lit]")].map((element) =>
        element.getAttribute("data-sidebar-item"),
      );
    expect(lit()).toEqual(["voices"]);
    view.unmount();
    const agents = renderShell("student", "/student/agents");
    expect(lit()).toEqual(["agents"]);
    agents.unmount();
    // Teams lights alone; the Mayaform pill stays on home.
    renderShell("student", "/student/teams");
    expect(lit()).toEqual(["teams"]);
  });
});

describe("collapse", () => {
  it("toggles from the edge button and remembers it", () => {
    const view = renderShell("student", "/student");
    expect(toggle().getAttribute("aria-label")).toBe("Collapse sidebar");
    expect(toggle().getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle());
    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe("1");
    expect(toggle().getAttribute("aria-label")).toBe("Expand sidebar");
    // Collapsed rows keep their names; the groups name their tiles.
    expect(nav().getByRole("link", { name: "Agents" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Brainform" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Logout" })).toBeTruthy();
    expect(
      screen.getByRole("link", {
        name: /Send to t330034059@mail\.bnbu\.edu\.cn/,
      }),
    ).toBeTruthy();
    view.unmount();
    renderShell("student", "/student");
    expect(toggle().getAttribute("aria-label")).toBe("Expand sidebar");
    fireEvent.click(toggle());
    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe("0");
  });

  it("toggles with Ctrl+B and ⌘+B, but not with Shift or inside rich text", () => {
    renderShell("student", "/student");
    fireEvent.keyDown(window, { key: "b", ctrlKey: true });
    expect(toggle().getAttribute("aria-label")).toBe("Expand sidebar");
    fireEvent.keyDown(window, { key: "B", metaKey: true });
    expect(toggle().getAttribute("aria-label")).toBe("Collapse sidebar");
    fireEvent.keyDown(window, { key: "b", ctrlKey: true, shiftKey: true });
    expect(toggle().getAttribute("aria-label")).toBe("Collapse sidebar");
    const editor = document.createElement("div");
    editor.contentEditable = "true";
    Object.defineProperty(editor, "isContentEditable", { value: true });
    document.body.append(editor);
    fireEvent.keyDown(editor, { key: "b", ctrlKey: true });
    expect(toggle().getAttribute("aria-label")).toBe("Collapse sidebar");
    editor.remove();
  });
});

describe("Live", () => {
  it("is a disabled row with a dim lamp while no class is live", async () => {
    renderShell("student", "/student");
    await waitFor(() => expect(state.api.classroomLive).toHaveBeenCalled());
    const off = document.querySelector('[data-tour="live"]')!;
    expect(off.tagName).toBe("SPAN");
    expect(off.getAttribute("aria-disabled")).toBe("true");
    expect(off.querySelector('[data-live-lamp="off"]')).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Live" })).toBeNull();
  });

  it("becomes a link with an ON AIR sticker, and a lit lamp when collapsed", async () => {
    state.api.classroomLive.mockResolvedValue({ debate_id: "d" });
    renderShell("student", "/student");
    const live = await screen.findByRole("link", { name: "Live" });
    expect(live.getAttribute("href")).toBe("/student/live");
    expect(live.getAttribute("data-tour")).toBe("live");
    const sticker = live.querySelector("[data-live-sticker]")!;
    expect(sticker.getAttribute("aria-hidden")).toBe("true");
    act(() => {
      fireEvent.click(toggle());
    });
    const collapsed = screen.getByRole("link", { name: "Live" });
    expect(collapsed.querySelector("[data-live-sticker]")).toBeNull();
    expect(collapsed.querySelector('[data-live-lamp="on"]')).toBeTruthy();
  });
});

describe("group headings", () => {
  it("are plain labels, and the first row of each group carries its tour place", () => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, "0");
    renderShell("student", "/student/agents");
    const groups = screen
      .getAllByRole("group")
      .filter((group) => group.hasAttribute("aria-labelledby"));
    expect(groups.length).toBeGreaterThan(0);
    for (const group of groups) {
      const heading = group.querySelector(
        `#${group.getAttribute("aria-labelledby")}`,
      );
      expect(heading).not.toBeNull();
      expect(heading!.querySelector("a, button")).toBeNull();
    }
    expect(
      document.querySelector('[data-tour="knowledge"]')?.textContent?.trim(),
    ).toBe("Agents");
    expect(
      document.querySelector('[data-tour="chat"]')?.textContent?.trim(),
    ).toBe("Chat with Agent");
    expect(
      nav().getByRole("link", { name: "Agents" }).getAttribute("aria-current"),
    ).toBe("page");
  });
});

describe("tour on a phone", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
    vi.stubGlobal(
      "matchMedia",
      (query: string) =>
        ({
          matches: query === "(max-width: 900px)",
          media: query,
          addEventListener() {},
          removeEventListener() {},
          addListener() {},
          removeListener() {},
        }) as unknown as MediaQueryList,
    );
  });
  afterEach(() => {
    window.sessionStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  it("opens the drawer for a sidebar step and closes it afterwards", async () => {
    window.sessionStorage.setItem(
      "maya.tour.state",
      JSON.stringify({
        ids: ["knowledge", "welcome"],
        index: 0,
        groupHref: "/student/groups/group-a",
      }),
    );
    window.history.replaceState(null, "", "/student");
    renderShell("student", "/student");
    const menu = () =>
      document.querySelector<HTMLElement>(
        'button[aria-controls="workspace-sidebar"]',
      )!;
    expect(menu().getAttribute("aria-expanded")).toBe("false");
    await waitFor(() =>
      expect(menu().getAttribute("aria-expanded")).toBe("true"),
    );
    act(() => {
      fireEvent.keyDown(window, { key: "ArrowRight" });
    });
    await waitFor(() =>
      expect(menu().getAttribute("aria-expanded")).toBe("false"),
    );
  });
});

describe("edge toggle", () => {
  it("straddles the right edge at its vertical middle (collapse-C)", () => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, "0");
    renderShell("student", "/student");
    const button = toggle();
    const sidebar = document.getElementById("workspace-sidebar")!;
    // The sidebar runs the full page; the toggle rides its pinned, viewport-tall layer.
    expect(button.parentElement?.hasAttribute("data-sidebar-pin")).toBe(true);
    expect(button.parentElement?.parentElement).toBe(sidebar);
    expect(sidebar.className).toContain("min-h-dvh");
    expect(button.parentElement!.className).toMatch(/(^| )sticky( |$)/);
    expect(button.parentElement!.className).toContain("h-dvh");
    expect(button.className).toContain("absolute");
    // collapse-C: the toggle rides the vertical middle of the edge.
    expect(button.className).toContain("top-[calc(50%-16px)]");
    // It sits clear of the rows (12px padding) and of the collapsed tiles.
    expect(button.className).toContain("-right-[22px]");
    act(() => {
      fireEvent.click(button);
    });
    expect(toggle().className).toContain("-right-[26px]");
    expect(toggle().className).toContain("top-[calc(50%-16px)]");
  });
});

describe("nav chrome", () => {
  it("keeps idle flat, active pink key, Logout key chrome", () => {
    renderShell("student", "/student/agents");
    const agents = nav().getByRole("link", { name: "Agents" });
    const teams = nav().getByRole("link", { name: "Teams" });
    const logout = screen.getByRole("button", { name: "Logout" });
    // Active Agents: pink key + press shadow.
    expect(agents.className).toContain("bg-main");
    expect(agents.className).toContain("border-border");
    expect(agents.className).toContain("shadow-[0_6px_0_#111]");
    // Idle Teams: flat at rest (transparent border/bg, no rest key shadow).
    expect(teams.className).toContain("border-transparent");
    expect(teams.className).toContain("bg-transparent");
    expect(teams.className).toContain("shadow-none");
    expect(teams.className).toContain("hover:bg-surface");
    expect(teams.className).toContain("hover:shadow-[0_6px_0_#111]");
    // Logout stays always-on key.
    expect(logout.className).toContain("bg-surface");
    expect(logout.className).toContain("border-border");
    expect(logout.className).toContain("shadow-[0_6px_0_#111]");
  });
});
