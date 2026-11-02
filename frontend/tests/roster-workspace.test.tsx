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
  useRouter: () => ({ push }),
  usePathname: () => "/teacher/roster",
}));

vi.mock("../components/session-provider", () => ({
  useSession: vi.fn(),
}));

import { useSession } from "../components/session-provider";
import { RosterWorkspace } from "../components/roster-workspace";
import { AppShell } from "../components/app-shell";
import { endTeacherEnter } from "../lib/teacher-visit";

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
    groups: vi.fn().mockResolvedValue([
      { id: groupId, course_id: courseId, name: "Team Aurora" },
      { id: "other-group", course_id: courseId, name: "Team Borealis" },
    ] as Group[]),
    updateCourseMember: vi.fn().mockResolvedValue(entry({})),
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

function mount(api: ReturnType<typeof apiForTeacher>) {
  const refresh = vi.fn().mockResolvedValue(null);
  mockedUseSession.mockReturnValue({
    api,
    refresh,
    user: {
      id: teacherId,
      courses: [{ course_id: courseId, role: "teacher" }],
      groups: [],
    },
  } as never);
  return render(
    <>
      <AppShell role="teacher">
        <RosterWorkspace />
      </AppShell>
    </>,
  );
}

describe("teacher account management", () => {
  afterEach(() => {
    endTeacherEnter();
    cleanup();
    vi.restoreAllMocks();
    push.mockReset();
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
    expect(screen.getByRole("heading", { name: "Accounts" }).className).toBe(
      "sr-only",
    );
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
    expect(within(own).queryByRole("button", { name: "Remove" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(1);
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

  it("confirms before removing and sends the new status", async () => {
    const api = apiForTeacher();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    mount(api);

    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    expect(confirm).toHaveBeenCalled();
    await waitFor(() =>
      expect(api.updateCourseMember).toHaveBeenCalledWith(courseId, studentId, {
        status: "inactive",
      }),
    );
  });

  it("keeps the account active when the teacher cancels the confirmation", async () => {
    const api = apiForTeacher();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    mount(api);

    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api.courseRoster).toHaveBeenCalled());
    expect(api.updateCourseMember).not.toHaveBeenCalled();
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
