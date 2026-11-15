import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CourseRoster, Group, RosterEntry } from "../lib/api";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: push }),
  usePathname: () => "/teacher/roster",
}));

vi.mock("../components/session-provider", () => ({
  useSession: vi.fn(),
}));

import { useSession } from "../components/session-provider";
import { RosterWorkspace } from "../components/roster-workspace";
import { AppShell } from "../components/app-shell";
import { endTeacherEnter } from "../lib/teacher-visit";
import { GROUP_SORT_STORAGE_KEY } from "../lib/group-sort";

const mockedUseSession = vi.mocked(useSession);
const courseId = "course-id";
const teacherId = "teacher-id";
const studentId = "student-id";
const catalogId = "catalog-id";
const groupId = "group-id";

function entry(overrides: Partial<RosterEntry>): RosterEntry {
  return {
    user_id: studentId,
    username: "new-student",
    display_name: "New Student",
    role: "student",
    status: "active",
    source: "database",
    editable: true,
    groups: [{ id: groupId, name: "Team Aurora" }],
    ...overrides,
  } as RosterEntry;
}

function roster(): CourseRoster {
  return {
    course_id: courseId,
    entries: [
      entry({}),
      entry({
        user_id: teacherId,
        username: "maya",
        display_name: "Maya",
        role: "teacher",
        source: "catalog",
        editable: false,
        groups: [{ id: groupId, name: "Team Aurora" }],
      }),
      entry({
        user_id: catalogId,
        username: "student-bowen-1",
        display_name: "Bowen Student 1",
        source: "catalog",
        editable: false,
      }),
    ],
  } as CourseRoster;
}

function apiForTeacher() {
  return {
    courses: vi.fn().mockResolvedValue([
      {
        id: courseId,
        code: "MAYA-101",
        name: "Cultural exchange",
        current_audio_debate_id: null,
      },
    ]),
    courseRoster: vi.fn().mockResolvedValue(roster()),
    createClass: vi.fn(),
    groups: vi.fn().mockResolvedValue([
      { id: groupId, course_id: courseId, name: "Team Aurora" },
      { id: "other-group", course_id: courseId, name: "Team Borealis" },
    ] as Group[]),
    updateCourseMember: vi.fn().mockResolvedValue(entry({})),
    deleteCourseMember: vi.fn().mockResolvedValue(undefined),
    resetStudentPassword: vi.fn().mockResolvedValue({
      user_id: studentId,
      username: "new-student",
      display_name: "New Student",
      password: "swift-otter-42",
    }),
    joinGroupAsTeacher: vi.fn().mockResolvedValue({}),
    leaveGroupAsTeacher: vi.fn().mockResolvedValue(undefined),
    courseAssessmentAttempts: vi.fn().mockResolvedValue([]),
  };
}

function mount(api: ReturnType<typeof apiForTeacher>, courseIds = [courseId]) {
  const refresh = vi.fn().mockResolvedValue(null);
  const context = {
    api,
    refresh,
    identityGeneration: 0,
    user: {
      id: teacherId,
      courses: courseIds.map((id) => ({ course_id: id, role: "teacher" })),
      groups: [],
    },
    selectTeacherCourse: vi.fn(async (id: string) => {
      context.user.courses = [
        ...context.user.courses.filter((item) => item.course_id === id),
        ...context.user.courses.filter((item) => item.course_id !== id),
      ];
      context.identityGeneration += 1;
      view.rerender(content());
    }),
  };
  mockedUseSession.mockReturnValue(context as never);
  const content = () => (
    <AppShell role="teacher">
      <RosterWorkspace />
    </AppShell>
  );
  const view = render(content());
  return view;
}

function apiForGroupSort() {
  const api = apiForTeacher();
  const groups: Group[] = [
    { id: "g10", course_id: courseId, name: "Group 10" },
    { id: "g2", course_id: courseId, name: "Group 2" },
    { id: "alpha", course_id: courseId, name: "Alpha" },
    { id: "empty", course_id: courseId, name: "Zulu" },
  ];
  api.groups.mockResolvedValue(groups);
  api.courseRoster.mockResolvedValue({
    course_id: courseId,
    entries: [
      entry({ groups: [groups[0], groups[1], groups[0]] }),
      entry({ groups: [groups[0], groups[1]] }),
      entry({ groups: [groups[2]] }),
      entry({ role: "teacher", groups: [groups[2]] }),
      entry({ role: "teacher", groups: [groups[2]] }),
      entry({ status: "inactive", groups: [groups[2]] }),
      entry({ groups: [] }),
    ].map((item, index) => ({ ...item, user_id: `sort-member-${index}` })),
  });
  return api;
}

function groupCardIds() {
  return within(screen.getByRole("region", { name: "Groups" }))
    .getAllByRole("button", { name: "Enter" })
    .map((card) => card.id);
}

const nameOrder = [
  "roster-group-alpha",
  "roster-group-g2",
  "roster-group-g10",
  "roster-group-empty",
];
const membersOrder = [
  "roster-group-g2",
  "roster-group-g10",
  "roster-group-alpha",
  "roster-group-empty",
];

describe("teacher account management", () => {
  afterEach(() => {
    endTeacherEnter();
    cleanup();
    vi.restoreAllMocks();
    localStorage.removeItem(GROUP_SORT_STORAGE_KEY);
    push.mockReset();
  });

  it("shows student counts on naturally ordered cards, excluding teachers and inactive students", async () => {
    mount(apiForGroupSort());
    await screen.findByTestId("group-sort");
    expect(groupCardIds()).toEqual(nameOrder);
    const cards = within(
      screen.getByRole("region", { name: "Groups" }),
    ).getAllByRole("button", { name: "Enter" });
    expect(
      cards.map(
        (card) => within(card).getByTestId("group-student-count").textContent,
      ),
    ).toEqual(["1", "2", "2", "0"]);
    expect(
      within(cards[0]).getByRole("img", { name: "1 student" }),
    ).toBeTruthy();
    expect(
      within(cards[1]).getByRole("img", { name: "2 students" }),
    ).toBeTruthy();
    expect(
      within(cards[3]).getByRole("img", { name: "0 students" }),
    ).toBeTruthy();
    for (const card of cards) {
      expect(card.getAttribute("data-ui-guide")).toBe("roster.openGroup");
    }
  });

  it("toggles the current-order label and sorts by student count with natural name ties", async () => {
    mount(apiForGroupSort());
    const key = await screen.findByRole("button", { name: "Sort groups: A–Z" });
    expect(key.textContent).toBe("A–Z");
    expect(key).toBe(screen.getByTestId("group-sort"));
    fireEvent.click(key);
    expect(key.getAttribute("aria-label")).toBe("Sort groups: Most members");
    expect(key.textContent).toBe("Most members");
    expect(groupCardIds()).toEqual(membersOrder);
    expect(localStorage.getItem(GROUP_SORT_STORAGE_KEY)).toBe("members");
    fireEvent.click(key);
    expect(key.getAttribute("aria-label")).toBe("Sort groups: A–Z");
    expect(key.textContent).toBe("A–Z");
    expect(groupCardIds()).toEqual(nameOrder);
    expect(localStorage.getItem(GROUP_SORT_STORAGE_KEY)).toBe("name");
  });

  it("keeps card counts and group sorting independent of the Members search", async () => {
    mount(apiForGroupSort());
    fireEvent.click(await screen.findByTestId("group-sort"));
    fireEvent.change(
      screen.getByRole("searchbox", {
        name: "Filter by name, username or group",
      }),
      {
        target: { value: "nobody-like-this" },
      },
    );
    expect(screen.getByText("No members match.")).toBeTruthy();
    expect(groupCardIds()).toEqual(membersOrder);
    expect(
      screen
        .getAllByTestId("group-student-count")
        .map((count) => count.textContent),
    ).toEqual(["2", "2", "1", "0"]);
  });

  it("restores the saved members order after a toggle and remount", async () => {
    const api = apiForGroupSort();
    const view = mount(api);
    fireEvent.click(await screen.findByTestId("group-sort"));
    view.unmount();
    mount(api);
    expect(
      await screen.findByRole("button", { name: "Sort groups: Most members" }),
    ).toBeTruthy();
    expect(groupCardIds()).toEqual(membersOrder);
  });

  it.each(["name", "invalid", "MEMBERS", ""])(
    "defaults to natural name order for stored value %j",
    async (value) => {
      localStorage.setItem(GROUP_SORT_STORAGE_KEY, value);
      mount(apiForGroupSort());
      expect(
        await screen.findByRole("button", { name: "Sort groups: A–Z" }),
      ).toBeTruthy();
      expect(groupCardIds()).toEqual(nameOrder);
    },
  );

  it.each(["getItem", "setItem"] as const)(
    "keeps sorting usable when storage %s throws",
    async (method) => {
      vi.spyOn(Storage.prototype, method).mockImplementation(() => {
        throw new Error("Storage unavailable");
      });
      mount(apiForGroupSort());
      fireEvent.click(
        await screen.findByRole("button", { name: "Sort groups: A–Z" }),
      );
      expect(
        screen.getByRole("button", { name: "Sort groups: Most members" }),
      ).toBeTruthy();
      expect(groupCardIds()).toEqual(membersOrder);
    },
  );

  it("creates a named class, refreshes access and opens its account list", async () => {
    const api = apiForTeacher();
    const created = {
      id: "new-class",
      code: "class-new",
      name: "History 2026",
      current_audio_debate_id: null,
    };
    api.createClass.mockResolvedValue(created);
    api.courseRoster.mockImplementation(async (id: string) =>
      id === created.id ? { course_id: id, entries: [] } : roster(),
    );
    mount(api);
    const session = mockedUseSession.mock.results.at(-1)!.value;
    vi.mocked(session.refresh).mockImplementation(async () => {
      session.user!.courses.push({ course_id: created.id, role: "teacher" });
      api.courses.mockResolvedValue([
        {
          id: courseId,
          code: "maya1001",
          name: "Maya1001",
          current_audio_debate_id: null,
        },
        created,
      ]);
    });
    fireEvent.click(await screen.findByRole("button", { name: "Add Class" }));
    fireEvent.change(screen.getByLabelText("Class name"), {
      target: { value: "History 2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create class" }));
    await waitFor(() =>
      expect(api.createClass).toHaveBeenCalledWith("History 2026"),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Class 2026, switch class",
      }),
    );
    expect(
      screen.getByRole("menuitemradio", { name: /History 2026/ }),
    ).toHaveProperty("ariaChecked", "true");
    await waitFor(() =>
      expect(api.courseRoster).toHaveBeenCalledWith(created.id),
    );
    expect(session.refresh).toHaveBeenCalled();
    expect(screen.queryByLabelText("Class name")).toBeNull();
  });

  it("keeps the class name and current roster when creation fails", async () => {
    const api = apiForTeacher();
    api.createClass.mockRejectedValue(new Error("unavailable"));
    mount(api);
    expect(await screen.findByText("New Student")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add Class" }));
    fireEvent.change(screen.getByLabelText("Class name"), {
      target: { value: "History 2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create class" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByLabelText("Class name")).toHaveProperty(
      "value",
      "History 2026",
    );
    expect(screen.getByText("New Student")).toBeTruthy();
  });

  it("switches the account list using the class menu", async () => {
    const api = apiForTeacher();
    api.courses.mockResolvedValue([
      {
        id: courseId,
        code: "maya1001",
        name: "Maya1001",
        current_audio_debate_id: null,
      },
      {
        id: "second-class",
        code: "maya1002",
        name: "Maya1002",
        current_audio_debate_id: null,
      },
    ]);
    api.courseRoster.mockImplementation(async (id: string) => ({
      course_id: id,
      entries: [
        entry({
          display_name:
            id === courseId ? "First class student" : "Second class student",
        }),
      ],
    }));
    mount(api, [courseId, "second-class"]);
    expect(await screen.findByText("First class student")).toBeTruthy();
    fireEvent.click(
      await screen.findByRole("button", { name: "Class 1001, switch class" }),
    );
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Maya1002" }));
    expect(screen.queryByText("First class student")).toBeNull();
    expect(await screen.findByText("Second class student")).toBeTruthy();
    expect(api.courseRoster).toHaveBeenLastCalledWith("second-class");
    fireEvent.click(
      await screen.findByRole("button", { name: "Class 1002, switch class" }),
    );
    expect(
      screen
        .getByRole("menuitemradio", { name: /Maya1002/ })
        .getAttribute("aria-checked"),
    ).toBe("true");
  });

  it("only exposes classes the teacher belongs to", async () => {
    const api = apiForTeacher();
    api.courses.mockResolvedValue([
      {
        id: courseId,
        code: "maya1001",
        name: "Maya1001",
        current_audio_debate_id: null,
      },
      {
        id: "second-class",
        code: "maya1002",
        name: "Maya1002",
        current_audio_debate_id: null,
      },
    ]);
    mount(api);
    expect(
      await screen.findByRole("link", { name: "Mayaform-1001" }),
    ).toBeTruthy();
    expect(screen.queryByTestId("class-switcher-trigger")).toBeNull();
    expect(
      screen.queryByRole("menuitemradio", { name: "Maya1002" }),
    ).toBeNull();
  });

  it("keeps Back and Done beside the member form while editing", async () => {
    const api = apiForTeacher();
    mount(api);
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    const sidebar = within(screen.getByRole("navigation"));
    expect(
      within(screen.getByRole("main")).getByRole("button", { name: "Back" }),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("main")).getByRole("button", { name: "Done" }),
    ).toBeTruthy();
    expect(sidebar.queryByRole("button", { name: "Back" })).toBeNull();
    const nameField = screen.getByLabelText("Display name");
    fireEvent.change(nameField, { target: { value: "Ada Lovelace" } });
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));

    await waitFor(() =>
      expect(api.updateCourseMember).toHaveBeenCalledWith(courseId, studentId, {
        display_name: "Ada Lovelace",
        group_name: "Team Aurora",
      }),
    );
  });

  it("offers edits only for accounts an edit can outlive a restart", async () => {
    const api = apiForTeacher();
    mount(api);
    await waitFor(() => expect(api.courseRoster).toHaveBeenCalled());

    const account = (await screen.findByText("new-student")).closest(
      ".account-row",
    ) as HTMLElement;
    // The group is the heading the row sits under, not repeated on the row.
    expect(
      (account.closest(".roster-section") as HTMLElement).querySelector(
        ".roster-section-title",
      )?.textContent,
    ).toBe("Team Aurora3");
    expect(within(account).queryByText("Team Aurora")).toBeNull();
    // Active is the normal state and is not labelled; only removed is.
    expect(within(account).queryByText(/^active$/i)).toBeNull();
    expect(screen.getByText("student-bowen-1")).toBeTruthy();
    // The name students see in their group leads; the sign-in name follows.
    expect(within(account).getByText("New Student").tagName).toBe("STRONG");
    expect(screen.queryByText("Self-registered")).toBeNull();
    expect(screen.queryByText("Student view")).toBeNull();
    expect(
      screen
        .getByRole("heading", { name: "Accounts", level: 1 })
        .closest("header"),
    ).not.toBeNull();
    // Removing source labels must not give catalog identities edit controls.
    expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(1);
    expect(screen.queryByText("Demo catalog")).toBeNull();
  });

  it("does not offer the teacher a status change on their own account", async () => {
    const api = apiForTeacher();
    const base = roster();
    api.courseRoster.mockResolvedValue({
      ...base,
      entries: (base.entries ?? []).map((item) =>
        item.user_id === teacherId
          ? { ...item, source: "database", editable: true }
          : item,
      ),
    });
    mount(api);

    const own = (await screen.findByText("maya")).closest(
      ".account-row",
    ) as HTMLElement;
    expect(within(own).getByRole("button", { name: "Edit" })).toBeTruthy();
    // 2026-11-03: Remove became a real Delete.
    expect(within(own).queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(1);
  });

  it("saves a renamed student", async () => {
    const api = apiForTeacher();
    mount(api);
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    const nameField = screen.getByLabelText("Display name");
    fireEvent.change(nameField, { target: { value: "Ada Lovelace" } });
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));

    await waitFor(() =>
      expect(api.updateCourseMember).toHaveBeenCalledWith(courseId, studentId, {
        display_name: "Ada Lovelace",
        group_name: "Team Aurora",
      }),
    );
  });

  it("suggests the group names already in the course", async () => {
    const api = apiForTeacher();
    const { container } = mount(api);
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    const options = Array.from(
      container.querySelectorAll("#roster-group-names option"),
    ).map((option) => option.getAttribute("value"));
    expect(options).toEqual(["Team Aurora", "Team Borealis"]);
  });

  it("confirms before deleting and deletes the account for real", async () => {
    const api = apiForTeacher();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    mount(api);

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(confirm).toHaveBeenCalled();
    expect(String(confirm.mock.calls[0][0])).toContain("cannot be undone");
    await waitFor(() =>
      expect(api.deleteCourseMember).toHaveBeenCalledWith(courseId, studentId),
    );
    expect(api.updateCourseMember).not.toHaveBeenCalled();
  });

  it("keeps the account active when the teacher cancels the confirmation", async () => {
    const api = apiForTeacher();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    mount(api);

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.courseRoster).toHaveBeenCalled());
    expect(api.updateCourseMember).not.toHaveBeenCalled();
    expect(api.deleteCourseMember).not.toHaveBeenCalled();
  });

  it("filters members by name, username or group", async () => {
    const api = apiForTeacher();
    mount(api);
    const box = await screen.findByRole("searchbox", {
      name: "Filter by name, username or group",
    });
    fireEvent.change(box, { target: { value: "new-stud" } });
    expect(screen.getByText("new-student")).toBeTruthy();
    expect(screen.queryByText("maya")).toBeNull();
    fireEvent.change(box, { target: { value: "nobody-like-this" } });
    expect(screen.getByText("No members match.")).toBeTruthy();
  });

  it("deletes every removed account at once from the Removed fold", async () => {
    const api = apiForTeacher();
    const old = [1, 2].map((index) =>
      entry({
        user_id: `removed-${index}`,
        username: `old-${index}`,
        display_name: `Old ${index}`,
        status: "inactive",
      }),
    );
    api.courseRoster.mockResolvedValue({
      ...roster(),
      entries: [...(roster().entries ?? []), ...old],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { container } = mount(api);
    await screen.findByText("old-1");
    const fold = container.querySelector(
      "details.roster-removed",
    ) as HTMLElement;
    fireEvent.click(
      within(fold).getByRole("button", { name: "Delete all removed" }),
    );
    await waitFor(() =>
      expect(api.deleteCourseMember.mock.calls.map((call) => call[1])).toEqual([
        "removed-1",
        "removed-2",
      ]),
    );
  });

  it("folds removed accounts away under Removed, where they can be restored", async () => {
    const api = apiForTeacher();
    const removed = entry({
      user_id: "removed-id",
      username: "old-student",
      display_name: "Old Student",
      status: "inactive",
    });
    api.courseRoster.mockResolvedValue({
      ...roster(),
      entries: [...(roster().entries ?? []), removed],
    });
    const { container } = mount(api);

    const members = await screen.findByRole("region", { name: /Members/ });
    // Three current members are counted; the removed one is not among them.
    expect(
      within(members)
        .getAllByText("3")
        .some((count) => !count.closest(".roster-section-title")),
    ).toBe(true);
    const fold = container.querySelector("details.roster-removed");
    expect(fold?.querySelector("summary")?.textContent).toBe("Removed · 1");
    expect(within(fold as HTMLElement).getByText("old-student")).toBeTruthy();
    expect(within(fold as HTMLElement).getByText("removed")).toBeTruthy();

    fireEvent.click(
      within(fold as HTMLElement).getByRole("button", { name: "Restore" }),
    );
    await waitFor(() =>
      expect(api.updateCourseMember).toHaveBeenCalledWith(
        courseId,
        "removed-id",
        { status: "active" },
      ),
    );
  });

  it("lists members group by group, with no group last", async () => {
    const api = apiForTeacher();
    api.courseRoster.mockResolvedValue({
      course_id: courseId,
      entries: [
        entry({
          user_id: "a",
          username: "zed",
          display_name: "Zed",
          groups: [],
        }),
        entry({
          user_id: "b",
          username: "yan",
          display_name: "Yan",
          groups: [{ id: "g10", name: "Group 10" }],
        }),
        entry({
          user_id: "c",
          username: "ada",
          display_name: "Ada",
          groups: [{ id: "g2", name: "Group 2" }],
        }),
        entry({
          user_id: "d",
          username: "bea",
          display_name: "Bea",
          groups: [{ id: "g2", name: "Group 2" }],
        }),
      ],
    } as CourseRoster);
    const { container } = mount(api);
    await screen.findByText("zed");

    const sections = [...container.querySelectorAll(".roster-section")].map(
      (section) => ({
        title: section.querySelector(".roster-section-title")?.textContent,
        people: [...section.querySelectorAll(".roster-headline strong")].map(
          (name) => name.textContent,
        ),
      }),
    );
    // Group 2 before Group 10, names sorted inside, the ungrouped last.
    expect(sections).toEqual([
      { title: "Group 22", people: ["Ada", "Bea"] },
      { title: "Group 101", people: ["Yan"] },
      { title: "No group1", people: ["Zed"] },
    ]);
  });

  it("shows an issued password once", async () => {
    const api = apiForTeacher();
    mount(api);

    fireEvent.click(await screen.findByRole("button", { name: "Reset" }));
    expect(await screen.findByText("swift-otter-42")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("swift-otter-42");
  });

  it("enters the group and opens that group's Studyform", async () => {
    const api = apiForTeacher();
    mount(api);

    const enter = await screen.findAllByRole("button", { name: "Enter" });
    fireEvent.click(enter[0]);
    await waitFor(() =>
      expect(api.joinGroupAsTeacher).toHaveBeenCalledWith(groupId),
    );
    expect(push).toHaveBeenCalledWith(
      `/student/agents?group_id=${encodeURIComponent(groupId)}`,
    );
  });

  it("leaves test results to Brainform Record", async () => {
    const api = apiForTeacher();
    mount(api);
    expect(await screen.findByText("new-student")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Test results" })).toBeNull();
    expect(api.courseAssessmentAttempts).not.toHaveBeenCalled();
  });
});
