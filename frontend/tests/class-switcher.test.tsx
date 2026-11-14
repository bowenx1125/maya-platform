import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  pathname: "/teacher/agents/example",
  replace: vi.fn(),
  user: {
    id: "teacher",
    courses: [
      { course_id: "a", role: "teacher" },
      { course_id: "b", role: "teacher" },
      { course_id: "student-class", role: "student" },
    ],
    groups: [],
  },
  api: { courses: vi.fn() },
  selectTeacherCourse: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useRouter: () => ({ replace: state.replace }),
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({ ...state, logout: vi.fn() }),
  RouteGuard: ({ children }: { children: ReactNode }) => children,
}));

import { ClassSwitcher } from "../components/class-switcher";
import { AppShell, SIDEBAR_COLLAPSED_KEY } from "../components/app-shell";
import { useTeacherClasses } from "../components/use-teacher-classes";
import TeacherLayout from "../app/teacher/layout";
import { beginTeacherEnter, endTeacherEnter } from "../lib/teacher-visit";

function homeLink(label?: ReactNode, className?: string, title?: string) {
  return (
    <a
      href="/teacher"
      className={className}
      title={title}
      data-testid="class-switcher-home"
    >
      {label}
    </a>
  );
}

function mount(collapsed = false, mobile = false) {
  return render(
    <ClassSwitcher collapsed={collapsed} mobile={mobile} homeLink={homeLink} />,
  );
}

async function trigger() {
  return screen.findByRole("button", { name: "Class 1001, switch class" });
}

beforeEach(() => {
  vi.clearAllMocks();
  state.api = { courses: vi.fn() };
  state.user.id = "teacher";
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
  state.pathname = "/teacher/agents/example";
  state.user.courses = [
    { course_id: "a", role: "teacher" },
    { course_id: "b", role: "teacher" },
    { course_id: "student-class", role: "student" },
  ];
  state.api.courses.mockResolvedValue([
    { id: "b", name: "Maya1002" },
    { id: "a", name: "Maya1001" },
    { id: "student-class", name: "Student class" },
    { id: "other", name: "Other class" },
  ]);
  state.selectTeacherCourse.mockResolvedValue(undefined);
  endTeacherEnter();
});

afterEach(() => {
  cleanup();
  endTeacherEnter();
  vi.unstubAllGlobals();
});

describe("class switcher", () => {
  it("renders the home and trigger, with only teacher classes as checked radios", async () => {
    mount();
    const button = await trigger();
    const home = screen.getByTestId("class-switcher-home");
    expect(home.textContent).toBe("Mayaform");
    expect(home.getAttribute("href")).toBe("/teacher");
    expect(home.title).toBe("Mayaform-1001");
    expect(button.getAttribute("aria-haspopup")).toBe("menu");
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("menu")).toBeNull();

    fireEvent.click(button);
    const menu = screen.getByRole("menu", { name: "Classes" });
    expect(menu.id).toBe(button.getAttribute("aria-controls"));
    const items = within(menu).getAllByRole("menuitemradio");
    expect(items.map((item) => item.title)).toEqual(["Maya1002", "Maya1001"]);
    expect(items.map((item) => item.getAttribute("aria-checked"))).toEqual([
      "false",
      "true",
    ]);
    expect(items[1].textContent).toBe("✓Maya1001Current");
    expect(document.activeElement).toBe(items[1]);
    expect(state.api.courses).toHaveBeenCalledTimes(1);
  });

  it("renders a single-class home pill without a trigger or menu", async () => {
    state.user.courses = [{ course_id: "a", role: "teacher" }];
    mount();
    await waitFor(() =>
      expect(screen.getByTestId("class-switcher-home").textContent).toBe(
        "Mayaform-1001",
      ),
    );
    expect(screen.queryByTestId("class-switcher-trigger")).toBeNull();
    expect(screen.queryByTestId("class-switcher-menu")).toBeNull();
  });

  it("keeps the full home wordmark and long non-Maya class name in the title", async () => {
    const name = "North Campus Evening Cohort Spring 2026";
    state.api.courses.mockResolvedValue([
      { id: "a", name },
      { id: "b", name: "Maya1002" },
    ]);
    mount();
    const button = await screen.findByRole("button", {
      name: `Class ${name}, switch class`,
    });
    expect(button.title).toBe(name);
    expect(button.textContent).toBe(name);
    expect(screen.getByTestId("class-switcher-home").textContent).toBe(
      "Mayaform",
    );
    expect(button.parentElement?.getAttribute("data-long-name")).toBe("true");
    fireEvent.click(button);
    expect(screen.getByTestId("class-switcher-item-a").title).toBe(name);
  });

  it.each([
    ...[
      "agents",
      "teams",
      "knowledge",
      "rag",
      "voices",
      "record",
      "debates",
      "chat",
      "roster",
      "quizzes",
    ].map((section) => [
      `/teacher/${section}/old-detail?group_id=old`,
      `/teacher/${section}`,
    ]),
    ["/teacher/chat/old?kind=team&group_id=old", "/teacher/chat?kind=team"],
    ["/teacher/chat/old?kind=agent", "/teacher/chat"],
    ["/teacher/agents/old?kind=team", "/teacher/agents"],
    ["/teacher", "/teacher"],
    ["/student/groups/old", "/teacher"],
  ])(
    "switches from %s to the same module list %s",
    async (url, destination) => {
      state.pathname = url.split("?")[0];
      window.history.replaceState(null, "", url);
      mount();
      const button = await trigger();
      fireEvent.click(button);
      fireEvent.click(screen.getByTestId("class-switcher-item-b"));
      await waitFor(() =>
        expect(state.replace).toHaveBeenCalledWith(destination),
      );
      expect(state.selectTeacherCourse).toHaveBeenCalledExactlyOnceWith("b");
      expect(button.getAttribute("aria-expanded")).toBe("false");
      expect(document.activeElement).toBe(button);
    },
  );

  it("does not select the current class or switch during teacher Enter", async () => {
    mount();
    const button = await trigger();
    fireEvent.click(button);
    fireEvent.click(screen.getByTestId("class-switcher-item-a"));
    expect(state.selectTeacherCourse).not.toHaveBeenCalled();
    fireEvent.click(button);
    beginTeacherEnter();
    fireEvent.click(screen.getByTestId("class-switcher-item-b"));
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(state.selectTeacherCourse).not.toHaveBeenCalled();
    expect(state.replace).not.toHaveBeenCalled();
  });

  it("blocks reopening and repeat selection while a switch is busy", async () => {
    let finish!: () => void;
    state.selectTeacherCourse.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    mount();
    const button = await trigger();
    fireEvent.click(button);
    fireEvent.click(screen.getByTestId("class-switcher-item-b"));
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(button);
    fireEvent.keyDown(button, { key: "ArrowDown" });
    fireEvent.click(screen.getByTestId("class-switcher-item-b"));
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(state.selectTeacherCourse).toHaveBeenCalledTimes(1);
    expect(state.replace).not.toHaveBeenCalled();
    await act(async () => finish());
    expect(button.getAttribute("aria-busy")).toBeNull();
    expect(state.replace).toHaveBeenCalledExactlyOnceWith("/teacher/agents");
  });

  it.each(["ArrowDown", "ArrowUp", "Enter", " "])(
    "opens with %s and supports cycling, Home/End and Escape focus return",
    async (key) => {
      mount();
      const button = await trigger();
      button.focus();
      fireEvent.keyDown(button, { key });
      const current = screen.getByTestId("class-switcher-item-a");
      const other = screen.getByTestId("class-switcher-item-b");
      expect(document.activeElement).toBe(current);
      fireEvent.keyDown(current, { key: "ArrowDown" });
      expect(document.activeElement).toBe(other);
      fireEvent.keyDown(other, { key: "ArrowUp" });
      expect(document.activeElement).toBe(current);
      fireEvent.keyDown(current, { key: "Home" });
      expect(document.activeElement).toBe(other);
      fireEvent.keyDown(other, { key: "End" });
      expect(document.activeElement).toBe(current);
      fireEvent.keyDown(current, { key: "Escape" });
      expect(button.getAttribute("aria-expanded")).toBe("false");
      expect(document.activeElement).toBe(button);
    },
  );

  it("closes when the open trigger is pressed again after focus moved into the menu", async () => {
    mount();
    const button = await trigger();
    fireEvent.click(button);
    const item = screen.getByTestId("class-switcher-item-a");
    expect(document.activeElement).toBe(item);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    // The press blurs the focused menu item before click. relatedTarget is
    // null in that blur, and React flushes the close before the click handler
    // runs. The click must still leave the menu closed.
    fireEvent.pointerDown(button);
    fireEvent.blur(item, { relatedTarget: null });
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("false");
    const menu = screen.getByTestId("class-switcher-menu");
    expect(menu.className).toContain("invisible");
    expect(menu.hasAttribute("inert")).toBe(true);
    expect(button.getAttribute("aria-expanded")).toBe("false");
  });

  it("does not keep the trigger press after the pointer is released outside", async () => {
    mount();
    const button = await trigger();
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    fireEvent.pointerDown(button, { button: 0 });
    fireEvent.pointerUp(document.body);
    fireEvent.pointerDown(document.body);
    expect(button.getAttribute("aria-expanded")).toBe("false");
  });

  it("closes on Tab, outside pointerdown and focus leaving the switcher", async () => {
    mount();
    const button = await trigger();
    fireEvent.click(button);
    fireEvent.keyDown(screen.getByTestId("class-switcher-item-a"), {
      key: "Tab",
    });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(button);
    fireEvent.pointerDown(document.body);
    expect(button.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(button);
    fireEvent.blur(screen.getByTestId("class-switcher-item-a"), {
      relatedTarget: document.body,
    });
    expect(button.getAttribute("aria-expanded")).toBe("false");
  });

  it("uses the collapsed class label and opens its menu to the right", async () => {
    mount(true);
    const button = await screen.findByRole("button", { name: "Class 1001" });
    expect(button.textContent).toBe("1001");
    expect(button.querySelector("svg")).toBeNull();
    fireEvent.click(button);
    expect(screen.getByRole("menu").parentElement?.className).toContain(
      "absolute top-full left-[calc(100%+12px)]",
    );
  });

  it("shows selection errors and releases busy without navigating", async () => {
    state.selectTeacherCourse.mockRejectedValueOnce(new Error("unavailable"));
    mount();
    const button = await trigger();
    fireEvent.click(button);
    fireEvent.click(screen.getByTestId("class-switcher-item-b"));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(button.getAttribute("aria-busy")).toBeNull();
    expect(state.replace).not.toHaveBeenCalled();
  });
});

describe("shared teacher class logic", () => {
  it("shows cached names on the first remount render before refresh resolves", async () => {
    const first = mount();
    await trigger();
    first.unmount();
    state.api.courses.mockReturnValue(new Promise(() => {}));
    const names: (string | undefined)[] = [];
    renderHook(() => {
      const value = useTeacherClasses();
      names.push(value.current?.name);
    });
    expect(names.length).toBeGreaterThan(0);
    expect(names.every((name) => name === "Maya1001")).toBe(true);
    expect(state.api.courses).toHaveBeenCalledTimes(2);
  });

  it("keeps the cached label if background refresh fails", async () => {
    const first = mount();
    await trigger();
    first.unmount();
    state.api.courses.mockRejectedValueOnce(new Error("unavailable"));
    mount();
    expect(screen.getByTestId("class-switcher-trigger").textContent).toBe(
      "1001",
    );
    await screen.findByRole("alert");
    expect(screen.getByTestId("class-switcher-trigger").textContent).toBe(
      "1001",
    );
  });

  it.each(["account", "membership", "session"])(
    "does not reuse another %s's cached names",
    async (change) => {
      const first = mount();
      await trigger();
      first.unmount();
      if (change === "account") state.user.id = "other-teacher";
      if (change === "membership")
        state.user.courses = [{ course_id: "a", role: "teacher" }];
      if (change === "session") state.api = { courses: vi.fn() };
      state.api.courses.mockReturnValue(new Promise(() => {}));
      const { result } = renderHook(() => useTeacherClasses());
      expect(result.current.current).toBeUndefined();
      expect(result.current.classes).toEqual([]);
    },
  );

  it("uses the selected class synchronously when teacher course order changes", async () => {
    const first = mount();
    await trigger();
    first.unmount();
    state.user.courses.reverse();
    state.api.courses.mockReturnValue(new Promise(() => {}));
    mount();
    expect(screen.getByTestId("class-switcher-trigger").textContent).toBe(
      "1002",
    );
  });

  it("guards current, Enter and busy calls independently of the menu", async () => {
    let finish!: () => void;
    state.selectTeacherCourse.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const { result } = renderHook(() => useTeacherClasses());
    await waitFor(() => expect(result.current.classes).toHaveLength(2));
    await act(async () => result.current.choose("a"));
    beginTeacherEnter();
    await act(async () => result.current.choose("b"));
    expect(state.selectTeacherCourse).not.toHaveBeenCalled();
    endTeacherEnter();
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.choose("b");
    });
    expect(result.current.busy).toBe("b");
    await act(async () => result.current.choose("b"));
    expect(state.selectTeacherCourse).toHaveBeenCalledExactlyOnceWith("b");
    await act(async () => {
      finish();
      await pending;
    });
    expect(result.current.busy).toBeNull();
  });
});

describe("teacher shell integration", () => {
  it("retains the layout's capsule node and label across distinct route pages", async () => {
    function AgentsPage() {
      return <p>Agents</p>;
    }
    function TeamsPage() {
      return <p>Teams</p>;
    }
    const view = render(
      <TeacherLayout>
        <AgentsPage />
      </TeacherLayout>,
    );
    const button = await trigger();
    state.api.courses.mockReturnValue(new Promise(() => {}));
    state.pathname = "/teacher/teams";
    view.rerender(
      <TeacherLayout>
        <TeamsPage />
      </TeacherLayout>,
    );
    expect(screen.getAllByTestId("class-switcher-trigger")).toEqual([button]);
    expect(button.textContent).toBe("1001");
    expect(state.api.courses).toHaveBeenCalledTimes(1);
    expect(within(screen.getByRole("main")).getByText("Teams")).toBeTruthy();
  });

  it("leaves the immersive stage without a workspace sidebar", () => {
    state.pathname = "/teacher/debates-beta/example/control";
    render(
      <TeacherLayout>
        <p>Stage</p>
      </TeacherLayout>,
    );
    expect(screen.getByText("Stage")).toBeTruthy();
    expect(screen.queryByTestId("class-switcher-home")).toBeNull();
  });

  function shell() {
    return render(
      <AppShell role="teacher">
        <p>Content</p>
      </AppShell>,
    );
  }

  it("places the switcher in navigation, outside the content, with no music key", async () => {
    shell();
    const button = await trigger();
    expect(button.closest("nav")).toBeTruthy();
    expect(
      within(screen.getByRole("main")).queryByTestId("class-switcher-home"),
    ).toBeNull();
    expect(screen.queryByRole("group", { name: "Classes" })).toBeNull();
    expect(screen.queryByRole("button", { name: /music/i })).toBeNull();
    const brandBlock = button.closest("[data-class-switcher]")?.parentElement;
    expect(brandBlock?.className).not.toContain("justify-self-end");
    expect(brandBlock?.querySelector("[data-music-key]")).toBeNull();
    fireEvent.click(button);
    expect(screen.getByRole("menu").parentElement?.className).not.toContain(
      "absolute",
    );
  });

  it("keeps the class label when the route changes and the class does not", async () => {
    const view = shell();
    const button = await trigger();
    expect(button.textContent).toContain("1001");
    const calls = state.api.courses.mock.calls.length;
    state.pathname = "/teacher/rag";
    view.rerender(
      <AppShell role="teacher">
        <p>Content</p>
      </AppShell>,
    );
    const again = await screen.findByRole("button", {
      name: "Class 1001, switch class",
    });
    expect(again.textContent).toContain("1001");
    expect(again.getAttribute("aria-expanded")).toBe("false");
    expect(state.api.courses.mock.calls.length).toBe(calls);
  });

  it("preserves home navigation, active state, brand dot and pending feedback", async () => {
    const view = shell();
    await trigger();
    const home = screen.getByTestId("class-switcher-home");
    expect(home.getAttribute("data-tour")).toBe("home");
    expect(home.getAttribute("aria-current")).toBeNull();
    expect(home.querySelector(".brand-dot")).toBeTruthy();
    fireEvent.click(home, { button: 0, ctrlKey: true });
    expect(home.getAttribute("aria-busy")).toBeNull();
    fireEvent.click(home, { button: 0 });
    expect(home.getAttribute("aria-busy")).toBe("true");
    expect(home.getAttribute("data-lit")).toBe("true");
    state.pathname = "/teacher";
    view.rerender(
      <AppShell role="teacher">
        <p>Content</p>
      </AppShell>,
    );
    await trigger();
    const arrived = screen.getByTestId("class-switcher-home");
    expect(arrived.getAttribute("aria-current")).toBe("page");
    expect(arrived.getAttribute("aria-busy")).toBeNull();
    expect(arrived.classList.contains("is-active")).toBe(true);
    expect(
      arrived.querySelector('span[aria-hidden="true"].absolute'),
    ).toBeTruthy();
  });

  it("renders the collapsed round home and class keys", async () => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, "1");
    shell();
    await screen.findByRole("button", { name: "Class 1001" });
    const home = screen.getByTestId("class-switcher-home");
    expect(home.getAttribute("aria-label")).toBe("Mayaform-1001");
    expect(home.className).toContain("rounded-full!");
    expect(home.textContent).toBe("");
    expect(home.querySelector(".brand-dot")).toBeTruthy();
  });

  it("renders one mobile switcher with a full-width in-flow menu and no drawer duplicate", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: query === "(max-width: 900px)",
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    shell();
    const button = await trigger();
    expect(button.closest("header")).toBeNull();
    expect(screen.getAllByTestId("class-switcher-trigger")).toHaveLength(1);
    fireEvent.click(button);
    expect(screen.getByRole("menu").parentElement?.className).toContain(
      "col-span-2",
    );
    expect(screen.getByRole("menu").parentElement?.className).not.toContain(
      "absolute",
    );
    expect(screen.queryByRole("button", { name: /music/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(
      within(screen.getByRole("navigation")).queryByTestId(
        "class-switcher-trigger",
      ),
    ).toBeNull();
    expect(screen.getAllByTestId("class-switcher-home")).toHaveLength(1);
  });

  it("keeps the music key on the student sidebar", async () => {
    state.user = {
      ...state.user,
      courses: [{ course_id: "student-class", role: "student" }],
    };
    render(
      <AppShell role="student">
        <p>Content</p>
      </AppShell>,
    );
    expect(await screen.findByRole("button", { name: /music/i })).toBeTruthy();
    expect(screen.queryByTestId("class-switcher-trigger")).toBeNull();
  });
});
