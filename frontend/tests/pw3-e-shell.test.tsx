import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "../components/locale";

const navigation = vi.hoisted(() => ({
  pathname: "/teacher",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => navigation,
}));

type Membership = { role: string };
const session = vi.hoisted(() => ({
  user: {
    display_name: "Teacher",
    courses: [] as (Membership & { course_id: string })[],
    groups: [] as (Membership & { group_id: string })[],
  },
  api: {} as Record<string, unknown>,
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({ ...session, logout: vi.fn(async () => undefined) }),
}));

import { AppShell } from "../components/app-shell";
import { PageAction } from "../components/page-action";

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

function renderStudentShell(pathname: string) {
  navigation.pathname = pathname;
  return render(
    <LocaleProvider initialLocale="en">
      <AppShell role="student">
        <p>Student content</p>
      </AppShell>
    </LocaleProvider>,
  );
}

const courseTeacherInTwoGroups = {
  display_name: "Maya",
  courses: [{ course_id: "course", role: "teacher" }],
  groups: [
    { group_id: "group-a", role: "admin" },
    { group_id: "group-b", role: "admin" },
  ],
};

function navHrefs() {
  return within(screen.getByRole("navigation"))
    .getAllByRole("link")
    .map((link) => link.getAttribute("href"));
}

beforeEach(() => {
  session.user = { display_name: "Teacher", courses: [], groups: [] };
  session.api = {};
});

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
    expect(screen.queryByRole("button", { name: "New" })).toBeNull();
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

  it("keeps page actions in the page and only destinations in the sidebar", () => {
    render(
      <AppShell role="teacher">
        <PageAction name="new" href="/teacher/debates/new" />
        <PageAction name="back" href="/teacher" />
        <PageAction name="done" onClick={vi.fn()} />
      </AppShell>,
    );
    const nav = within(screen.getByRole("navigation"));
    for (const name of ["New", "Back", "Done"]) {
      expect(nav.queryByRole("link", { name })).toBeNull();
      expect(nav.queryByRole("button", { name })).toBeNull();
    }
    const main = within(screen.getByRole("main"));
    expect(main.getByRole("link", { name: "New" }).getAttribute("href")).toBe(
      "/teacher/debates/new",
    );
    expect(main.getByRole("link", { name: "Back" })).toBeTruthy();
    expect(main.getByRole("button", { name: "Done" })).toBeTruthy();
  });

  it("makes a routed action that cannot run a disabled button, not a live link", () => {
    render(<PageAction name="new" href="/teacher/debates/new" disabled />);
    expect(screen.queryByRole("link", { name: "New" })).toBeNull();
    expect(
      (screen.getByRole("button", { name: "New" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("submits the form Done belongs to only once it is valid", () => {
    const submit = vi.fn();
    render(
      <form
        id="active-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <input aria-label="Name" required />
        <PageAction name="done" form="active-form" />
      </form>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(submit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Valid" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(submit).toHaveBeenCalledTimes(1);
  });
});

describe("student shell navigation", () => {
  afterEach(() => cleanup());

  it("sends a student's Mayaform to the student home", () => {
    session.user = {
      display_name: "Kaikai",
      courses: [{ course_id: "course", role: "student" }],
      groups: [{ group_id: "group-a", role: "member" }],
    };
    renderStudentShell("/student");
    const home = within(screen.getByRole("navigation")).getByRole("link", {
      name: "Mayaform",
    });
    expect(home.getAttribute("href")).toBe("/student");
    expect(home.getAttribute("aria-current")).toBe("page");
  });

  it("sends a course teacher's Mayaform to the teacher home from inside a group", () => {
    session.user = courseTeacherInTwoGroups;
    renderStudentShell("/student/groups/group-b");
    const nav = within(screen.getByRole("navigation"));
    const home = nav.getByRole("link", { name: "Mayaform" });
    expect(home.getAttribute("href")).toBe("/teacher");
    expect(home.getAttribute("aria-current")).toBeNull();
    expect(nav.queryByText("Homeward")).toBeNull();
    expect(navHrefs().filter((href) => href?.startsWith("/teacher"))).toEqual([
      "/teacher",
    ]);
  });

  it("points the group links at the group in the URL, not the first membership", () => {
    session.user = courseTeacherInTwoGroups;
    renderStudentShell("/student/groups/group-b/knowledge");
    expect(navHrefs()).toEqual([
      "/teacher",
      "/student/chat",
      "/student/groups/group-b",
      "/student/groups/group-b/knowledge",
      "/student/groups/group-b/voices",
    ]);
    expect(
      within(screen.getByRole("navigation"))
        .getByRole("link", { name: "Knowledge" })
        .getAttribute("aria-current"),
    ).toBe("page");
  });

  it("falls back to the only group on pages that name none", () => {
    session.user = {
      display_name: "Kaikai",
      courses: [{ course_id: "course", role: "student" }],
      groups: [{ group_id: "group-a", role: "member" }],
    };
    session.api = { agent: vi.fn(), version: vi.fn() };
    renderStudentShell("/student/agents/agent-a");
    expect(
      within(screen.getByRole("navigation"))
        .getByRole("link", { name: "Workspace" })
        .getAttribute("href"),
    ).toBe("/student/groups/group-a");
    expect(session.api.agent).not.toHaveBeenCalled();
  });

  it("asks which group owns an Agent before linking a member of several groups", async () => {
    session.user = courseTeacherInTwoGroups;
    let resolveAgent!: (agent: { id: string; group_id: string }) => void;
    session.api = {
      version: vi.fn().mockResolvedValue({ id: "v-b", agent_id: "agent-b" }),
      agent: vi.fn(
        () =>
          new Promise((resolve) => {
            resolveAgent = resolve;
          }),
      ),
    };
    renderStudentShell("/student/agent-versions/v-b/edit");
    const nav = within(screen.getByRole("navigation"));
    await waitFor(() =>
      expect(session.api.agent).toHaveBeenCalledWith("agent-b"),
    );
    // Until the owner is known there is no group link to follow, rather than
    // one that leads into the first group.
    expect(nav.queryByRole("link", { name: "Workspace" })).toBeNull();
    resolveAgent({ id: "agent-b", group_id: "group-b" });
    const workspace = await nav.findByRole("link", { name: "Workspace" });
    expect(workspace.getAttribute("href")).toBe("/student/groups/group-b");
    expect(workspace.getAttribute("aria-current")).toBe("page");
    expect(nav.getByRole("link", { name: "Voices" }).getAttribute("href")).toBe(
      "/student/groups/group-b/voices",
    );
  });
});
