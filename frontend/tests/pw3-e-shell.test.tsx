import { cleanup, render, screen, within } from "@testing-library/react";
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

  it("exposes Dashboard, Debates and the beta stage as primary navigation links", () => {
    renderTeacherShell("/teacher");

    const primaryNavigation = within(screen.getByRole("navigation"));
    const links = primaryNavigation.getAllByRole("link");
    // Debates (beta) is a sibling entry, not a replacement: the classic
    // Debates link stays exactly where it was.
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/teacher",
      "/teacher/debates",
      "/teacher/debates-beta",
    ]);
    expect(
      primaryNavigation.getByRole("link", { name: "Dashboard" }).className,
    ).toContain("active");
    expect(
      primaryNavigation
        .getByRole("link", { name: "Dashboard" })
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

    expect(screen.getByRole("button", { name: "Log out" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Maya" })).toBeTruthy();
  });

  it("keeps the debate item active for nested create and control routes", () => {
    renderTeacherShell("/teacher/debates/example-debate/control");

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
      primaryNavigation.getByRole("link", { name: "Dashboard" }).className,
    ).not.toContain("active");
  });

  it("keeps Dashboard active for nested published Agent inspection routes", () => {
    renderTeacherShell("/teacher/agents/agent-id");

    const primaryNavigation = within(screen.getByRole("navigation"));
    expect(
      primaryNavigation.getByRole("link", { name: "Dashboard" }).className,
    ).toContain("active");
    expect(
      primaryNavigation
        .getByRole("link", { name: "Dashboard" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      primaryNavigation.getByRole("link", { name: "Debates" }).className,
    ).not.toContain("active");
  });
});
