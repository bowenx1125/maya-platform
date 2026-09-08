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

  it("exposes Home, Classroom as primary navigation links", () => {
    renderTeacherShell("/teacher");

    const primaryNavigation = within(screen.getByRole("navigation"));
    const links = primaryNavigation.getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/teacher",
      "/teacher/debates",
    ]);
    expect(
      primaryNavigation.getByRole("link", { name: "Home" }).className,
    ).toContain("active");
    expect(
      primaryNavigation
        .getByRole("link", { name: "Home" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      primaryNavigation.getByRole("link", { name: "Classroom" }).className,
    ).not.toContain("active");
    expect(
      primaryNavigation
        .getByRole("link", { name: "Classroom" })
        .getAttribute("aria-current"),
    ).toBeNull();

    expect(screen.getByRole("button", { name: "Log out" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Mayaform" })).toBeTruthy();
  });

  it.each([
    "/teacher/debates/example-debate/control",
    "/teacher/debates-beta/example-debate/control",
  ])("keeps Classroom active for %s", (path) => {
    renderTeacherShell(path);

    const primaryNavigation = within(screen.getByRole("navigation"));
    expect(
      primaryNavigation.getByRole("link", { name: "Classroom" }).className,
    ).toContain("active");
    expect(
      primaryNavigation
        .getByRole("link", { name: "Classroom" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      primaryNavigation.getByRole("link", { name: "Home" }).className,
    ).not.toContain("active");
  });

  it("keeps Home active for nested published Agent inspection routes", () => {
    renderTeacherShell("/teacher/agents/agent-id");

    const primaryNavigation = within(screen.getByRole("navigation"));
    expect(
      primaryNavigation.getByRole("link", { name: "Home" }).className,
    ).toContain("active");
    expect(
      primaryNavigation
        .getByRole("link", { name: "Home" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      primaryNavigation.getByRole("link", { name: "Classroom" }).className,
    ).not.toContain("active");
  });
});
