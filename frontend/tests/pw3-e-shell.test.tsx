import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { readFileSync } from "node:fs";
import { basename, join } from "node:path";
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
  refresh: vi.fn(async () => null),
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({ ...session, logout: vi.fn(async () => undefined) }),
}));

import { AppShell } from "../components/app-shell";
import { PageAction } from "../components/page-action";
import { WorkspaceAction } from "../components/workspace-actions";

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
  session.refresh.mockClear();
});

describe("PW3-E teacher information architecture", () => {
  afterEach(() => cleanup());

  it("exposes the five primary destinations, then the teacher's Debates and Accounts", () => {
    renderTeacherShell("/teacher");

    const navigationElement = screen.getByRole("navigation");
    const primaryNavigation = within(navigationElement);
    const destinations = [
      ...navigationElement.querySelectorAll("a, [aria-disabled='true']"),
    ];
    expect(destinations.map((item) => item.textContent?.trim())).toEqual([
      "Mayaform",
      "Studyform",
      "Brainform",
      "Chatform",
      "Debates",
      "Accounts",
    ]);
    expect(
      primaryNavigation
        .getAllByRole("link")
        .map((link) => link.getAttribute("href")),
    ).toEqual([
      "/teacher",
      "/teacher/studyform",
      "/teacher/knowledge",
      "/teacher/chat",
      "/teacher/debates",
      "/teacher/roster",
    ]);
    expect(
      primaryNavigation.getByRole("link", { name: "Brainform" }),
    ).toBeTruthy();
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
      primaryNavigation.getByRole("link", { name: "Accounts" }).className,
    ).not.toContain("active");

    expect(screen.getByRole("button", { name: "Logout" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "New" })).toBeNull();
    expect(screen.getAllByRole("link", { name: "Mayaform" })).toHaveLength(1);
    expect(document.querySelectorAll(".brand-dot")).toHaveLength(1);
  });

  it.each([
    "/teacher/debates/new",
    "/teacher/debates/example-debate/control",
    "/teacher/debates-beta/example-debate/control",
  ])("keeps Debates selected inside its nested route %s", (path) => {
    renderTeacherShell(path);

    const primaryNavigation = within(screen.getByRole("navigation"));
    expect(
      primaryNavigation
        .getByRole("link", { name: "Debates" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      primaryNavigation.getByRole("link", { name: "Mayaform" }).className,
    ).not.toContain("active");
  });

  it("keeps the sidebar labels on a view-transition layer above the moving highlight", () => {
    renderTeacherShell("/teacher");

    expect(screen.getByRole("navigation").classList).toContain("nav-links");
    const frontendRoot =
      basename(process.cwd()) === "frontend"
        ? process.cwd()
        : join(process.cwd(), "frontend");
    const globals = readFileSync(
      join(frontendRoot, "app", "globals.css"),
      "utf8",
    );
    const shell = readFileSync(
      join(frontendRoot, "components", "app-shell.module.css"),
      "utf8",
    );
    expect(globals).toMatch(
      /\.nav-links\s*\{[^}]*view-transition-name:\s*nav-links/s,
    );
    expect(globals).toMatch(
      /::view-transition-group\(nav-links\)\s*\{[^}]*z-index:\s*1/s,
    );
    expect(shell).not.toContain("view-transition-name");
  });

  it("keeps Studyform active for legacy nested Agent routes", () => {
    renderTeacherShell("/teacher/agents/agent-id");

    const primaryNavigation = within(screen.getByRole("navigation"));
    expect(
      primaryNavigation.getByRole("link", { name: "Studyform" }).className,
    ).toContain("active");
    expect(
      primaryNavigation
        .getByRole("link", { name: "Studyform" })
        .getAttribute("aria-current"),
    ).toBe("page");
  });

  it("renders the current page actions in the left sidebar", () => {
    render(
      <AppShell role="teacher">
        <PageAction name="new" href="/teacher/debates/new" />
        <PageAction name="back" href="/teacher" />
        <PageAction name="done" onClick={vi.fn()} />
      </AppShell>,
    );
    const nav = within(screen.getByRole("navigation"));
    expect(nav.getByRole("link", { name: "New" }).getAttribute("href")).toBe(
      "/teacher/debates/new",
    );
    expect(nav.getByRole("link", { name: "Back" }).getAttribute("href")).toBe(
      "/teacher",
    );
    expect(nav.getByRole("button", { name: "Done" })).toBeTruthy();
    expect(
      within(screen.getByRole("main")).queryByRole("link", { name: "New" }),
    ).toBeNull();
    expect(
      within(screen.getByRole("main")).queryByRole("link", { name: "Back" }),
    ).toBeNull();
    expect(
      within(screen.getByRole("main")).queryByRole("button", { name: "Done" }),
    ).toBeNull();
  });

  it("retains registered sidebar actions for Brainform and General Chats", () => {
    render(
      <AppShell role="student">
        <WorkspaceAction name="new" href="/student/knowledge/new" />
      </AppShell>,
    );
    const nav = within(screen.getByRole("navigation"));
    // Students have no Brainform entry since 2026-10-20 (RAG and Record
    // moved into Studyform).
    expect(nav.queryByRole("link", { name: "Brainform" })).toBeNull();
    expect(nav.getByRole("link", { name: "New" }).getAttribute("href")).toBe(
      "/student/knowledge/new",
    );
  });

  it("makes a routed action that cannot run a disabled button, not a live link", () => {
    render(
      <AppShell role="teacher">
        <PageAction name="new" href="/teacher/debates/new" disabled />
      </AppShell>,
    );
    const nav = within(screen.getByRole("navigation"));
    expect(nav.queryByRole("link", { name: "New" })).toBeNull();
    expect(
      (nav.getByRole("button", { name: "New" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("submits the form Done belongs to only once it is valid", () => {
    const submit = vi.fn();
    render(
      <AppShell role="teacher">
        <form
          id="active-form"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <input aria-label="Name" required />
          <PageAction name="done" form="active-form" />
        </form>
      </AppShell>,
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

  it("keeps Studyform lit while a student makes a new Agent", () => {
    session.user = {
      display_name: "Kaikai",
      courses: [{ course_id: "course", role: "student" }],
      groups: [{ group_id: "group-a", role: "member" }],
    };
    renderStudentShell("/student/groups/group-a/agents/new");
    const nav = within(screen.getByRole("navigation"));
    expect(
      nav.getByRole("link", { name: "Studyform" }).getAttribute("aria-current"),
    ).toBe("page");
    expect(
      nav.getByRole("link", { name: "Mayaform" }).getAttribute("aria-current"),
    ).toBeNull();
  });

  it("treats a teacher inside a student group as a visit opened from Accounts", () => {
    session.user = courseTeacherInTwoGroups;
    const leaveGroupAsTeacher = vi.fn(async () => undefined);
    session.api = { leaveGroupAsTeacher };
    renderStudentShell("/student/groups/group-b");
    const nav = within(screen.getByRole("navigation"));
    const home = nav.getByRole("link", { name: "Mayaform" });
    expect(home.getAttribute("href")).toBe("/teacher");
    expect(home.getAttribute("aria-current")).toBeNull();
    // Inside the visit the sidebar is the group's, as its members see it.
    const studyform = nav.getByRole("link", { name: "Studyform" });
    expect(studyform.getAttribute("href")).toBe("/student/groups/group-b");
    expect(studyform.getAttribute("aria-current")).toBe("page");
    expect(
      nav.getByRole("link", { name: "Brainform" }).getAttribute("href"),
    ).toBe("/teacher/knowledge?group_id=group-b");
    expect(
      nav.getByRole("link", { name: "Chatform" }).getAttribute("href"),
    ).toBe("/teacher/chat?group_id=group-b");
    expect(
      nav.getByRole("link", { name: "Accounts" }).getAttribute("aria-current"),
    ).toBeNull();
    expect(nav.getByRole("link", { name: "Back" }).getAttribute("href")).toBe(
      "/teacher/roster",
    );
    expect(nav.queryByRole("link", { name: "Homeward" })).toBeNull();
    expect(leaveGroupAsTeacher).not.toHaveBeenCalled();
  });

  it.each([
    ["Brainform", "/teacher/knowledge"],
    ["Chatform", "/teacher/chat"],
  ])(
    "keeps the visit while the teacher is in that group's %s",
    async (label, path) => {
      session.user = courseTeacherInTwoGroups;
      const leaveGroupAsTeacher = vi.fn(async () => undefined);
      session.api = { leaveGroupAsTeacher };
      window.history.replaceState(null, "", `${path}?group_id=group-b`);
      try {
        renderTeacherShell(path);
        const nav = within(screen.getByRole("navigation"));
        await waitFor(() =>
          expect(
            nav.getByRole("link", { name: "Back" }).getAttribute("href"),
          ).toBe("/teacher/roster"),
        );
        expect(
          nav.getByRole("link", { name: label }).getAttribute("aria-current"),
        ).toBe("page");
        expect(
          nav.getByRole("link", { name: "Studyform" }).getAttribute("href"),
        ).toBe("/student/groups/group-b");
        await waitFor(() =>
          expect(leaveGroupAsTeacher).toHaveBeenCalledWith("group-a"),
        );
        expect(leaveGroupAsTeacher).not.toHaveBeenCalledWith("group-b");
      } finally {
        window.history.replaceState(null, "", "/");
      }
    },
  );

  it("keeps a visiting teacher's sidebar in the group on its Agent pages", () => {
    session.user = {
      display_name: "Maya",
      courses: [{ course_id: "course", role: "teacher" }],
      groups: [{ group_id: "group-b", role: "admin" }],
    };
    const leaveGroupAsTeacher = vi.fn(async () => undefined);
    session.api = { leaveGroupAsTeacher, agent: vi.fn(), version: vi.fn() };
    renderStudentShell("/student/agents/agent-b");
    const nav = within(screen.getByRole("navigation"));
    const studyform = nav.getByRole("link", { name: "Studyform" });
    expect(studyform.getAttribute("href")).toBe("/student/groups/group-b");
    expect(studyform.getAttribute("aria-current")).toBe("page");
    expect(
      nav.getByRole("link", { name: "Brainform" }).getAttribute("href"),
    ).toBe("/teacher/knowledge?group_id=group-b");
    expect(leaveGroupAsTeacher).not.toHaveBeenCalled();
  });

  it("ends the visit on the teacher's own Chatform", async () => {
    session.user = courseTeacherInTwoGroups;
    const leaveGroupAsTeacher = vi.fn(async () => undefined);
    session.api = { leaveGroupAsTeacher };
    renderTeacherShell("/teacher/chat");
    await waitFor(() => expect(leaveGroupAsTeacher).toHaveBeenCalledTimes(2));
    expect(
      within(screen.getByRole("navigation"))
        .getByRole("link", { name: "Chatform" })
        .getAttribute("href"),
    ).toBe("/teacher/chat");
  });

  it("removes every temporary group visit once the teacher is back on a teacher page", async () => {
    session.user = courseTeacherInTwoGroups;
    const leaveGroupAsTeacher = vi.fn(async () => undefined);
    session.api = { leaveGroupAsTeacher };
    renderTeacherShell("/teacher/roster");
    await waitFor(() => expect(leaveGroupAsTeacher).toHaveBeenCalledTimes(2));
    expect(leaveGroupAsTeacher).toHaveBeenCalledWith("group-a");
    expect(leaveGroupAsTeacher).toHaveBeenCalledWith("group-b");
    await waitFor(() => expect(session.refresh).toHaveBeenCalledTimes(1));
    expect(
      within(screen.getByRole("navigation")).queryByRole("link", {
        name: "Back",
      }),
    ).toBeNull();
  });

  it("points the group links at the group in the URL, not the first membership", () => {
    session.user = {
      display_name: "Learner",
      courses: [{ course_id: "course", role: "student" }],
      groups: [
        { group_id: "group-a", role: "member" },
        { group_id: "group-b", role: "member" },
      ],
    };
    renderStudentShell("/student/groups/group-b/knowledge");
    expect(navHrefs()).toEqual([
      "/student",
      "/student/groups/group-b",
      "/student/chat",
    ]);
    expect(
      within(screen.getByRole("navigation")).queryByRole("link", {
        name: "Brainform",
      }),
    ).toBeNull();
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
        .getByRole("link", { name: "Studyform" })
        .getAttribute("href"),
    ).toBe("/student/groups/group-a");
    expect(session.api.agent).not.toHaveBeenCalled();
  });

  it("keeps a multi-group student's Studyform link on the Agent's real group", async () => {
    session.user = {
      display_name: "Learner",
      courses: [{ course_id: "course", role: "student" }],
      groups: [
        { group_id: "group-a", role: "member" },
        { group_id: "group-b", role: "member" },
      ],
    };
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
    expect(
      nav.getByRole("link", { name: "Studyform" }).getAttribute("href"),
    ).toBe("/student#student-groups");
    resolveAgent({ id: "agent-b", group_id: "group-b" });
    await waitFor(() =>
      expect(
        nav.getByRole("link", { name: "Studyform" }).getAttribute("href"),
      ).toBe("/student/groups/group-b"),
    );
    const studyform = nav.getByRole("link", { name: "Studyform" });
    expect(studyform.getAttribute("href")).toBe("/student/groups/group-b");
    expect(studyform.getAttribute("aria-current")).toBe("page");
    expect(nav.queryByRole("link", { name: "Voices" })).toBeNull();
  });
});
