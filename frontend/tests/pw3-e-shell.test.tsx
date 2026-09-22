import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "../components/locale";

const navigation = vi.hoisted(() => ({
  pathname: "/teacher",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => navigation,
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    user: {
      display_name: "Teacher",
      groups: [],
    },
    logout: vi.fn(async () => undefined),
  }),
}));

import { AppShell } from "../components/app-shell";
import { WorkspaceNew } from "../components/workspace-new";

function renderTeacherShell(pathname: string) {
  navigation.pathname = pathname;
  return render(
    <LocaleProvider initialLocale="en">
      <AppShell role="teacher">
        <p>Teacher content</p>
      </AppShell>
    </LocaleProvider>,
  );
}

describe("PW3-E teacher information architecture", () => {
  afterEach(() => cleanup());

  it("exposes Mayaform, Chat, Debates and Accounts as primary navigation links", () => {
    renderTeacherShell("/teacher");

    const primaryNavigation = within(screen.getByRole("navigation"));
    const links = primaryNavigation.getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/teacher",
      "/teacher/chat",
      "/teacher/debates",
      "/teacher/roster",
    ]);
    expect(
      primaryNavigation.getByRole("link", { name: "Mayaform" }).className,
    ).toContain("active");
    expect(
      primaryNavigation
        .getByRole("link", { name: "Mayaform" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      primaryNavigation.getByRole("link", { name: "Debates" }).className,
    ).not.toContain("active");
    expect(
      primaryNavigation
        .getByRole("link", { name: "Debates" })
        .getAttribute("aria-current"),
    ).toBeNull();

    expect(screen.getByRole("button", { name: "Logout" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
    ).toBe(true);
    expect(screen.getAllByRole("link", { name: "Mayaform" })).toHaveLength(1);
    expect(document.querySelectorAll(".brand-dot")).toHaveLength(1);
  });

  it.each([
    "/teacher/debates/example-debate/control",
    "/teacher/debates-beta/example-debate/control",
  ])("keeps Debates active for %s", (path) => {
    renderTeacherShell(path);

    const primaryNavigation = within(screen.getByRole("navigation"));
    expect(
      primaryNavigation.getByRole("link", { name: "Debates" }).className,
    ).toContain("active");
    expect(
      primaryNavigation
        .getByRole("link", { name: "Debates" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      primaryNavigation.getByRole("link", { name: "Mayaform" }).className,
    ).not.toContain("active");
  });

  it("keeps Mayaform active for nested published Agent inspection routes", () => {
    renderTeacherShell("/teacher/agents/agent-id");

    const primaryNavigation = within(screen.getByRole("navigation"));
    expect(
      primaryNavigation.getByRole("link", { name: "Mayaform" }).className,
    ).toContain("active");
    expect(
      primaryNavigation
        .getByRole("link", { name: "Mayaform" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      primaryNavigation.getByRole("link", { name: "Debates" }).className,
    ).not.toContain("active");
  });

  it("places the page's New action in navigation and disables it when the page removes it", () => {
    const run = vi.fn();
    const view = render(
      <AppShell role="teacher">
        <WorkspaceNew onClick={run} />
        <p>Content</p>
      </AppShell>,
    );
    const nav = within(screen.getByRole("navigation"));
    fireEvent.click(nav.getByRole("button", { name: "New" }));
    expect(run).toHaveBeenCalledTimes(1);
    expect(
      within(screen.getByRole("main")).queryByRole("button", { name: "New" }),
    ).toBeNull();
    view.rerender(
      <AppShell role="teacher">
        <p>Read only</p>
      </AppShell>,
    );
    expect(
      nav.getByRole("button", { name: "New" }).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("uses a real navigation link for routed creation", () => {
    render(
      <AppShell role="teacher">
        <WorkspaceNew href="/teacher/debates/new" />
      </AppShell>,
    );
    expect(
      within(screen.getByRole("navigation"))
        .getByRole("link", { name: "New" })
        .getAttribute("href"),
    ).toBe("/teacher/debates/new");
  });
});
