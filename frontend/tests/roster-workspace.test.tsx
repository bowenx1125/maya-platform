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
import { LocaleProvider } from "../components/locale";

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
  };
}

function mount(api: ReturnType<typeof apiForTeacher>, locale: "en" | "zh") {
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
    <LocaleProvider initialLocale={locale}>
      <AppShell role="teacher">
        <RosterWorkspace />
      </AppShell>
    </LocaleProvider>,
  );
}

describe("teacher account management", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    push.mockReset();
  });

  it("keeps Back and Done beside the member form while editing", async () => {
    const api = apiForTeacher();
    mount(api, "en");
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    const sidebar = within(screen.getByRole("navigation"));
    expect(sidebar.getByRole("button", { name: "Back" })).toBeTruthy();
    expect(sidebar.getByRole("button", { name: "Done" })).toBeTruthy();
    expect(
      within(screen.getByRole("main")).queryByRole("button", {
        name: "Back",
      }),
    ).toBeNull();
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
    mount(api, "en");
    await waitFor(() => expect(api.courseRoster).toHaveBeenCalled());

    const account = (await screen.findByText("new-student")).closest(
      ".account-row",
    ) as HTMLElement;
    expect(within(account).getByText("Team Aurora")).toBeTruthy();
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
    mount(api, "en");

    const own = (await screen.findByText("maya")).closest(
      ".account-row",
    ) as HTMLElement;
    expect(within(own).getByRole("button", { name: "Edit" })).toBeTruthy();
    expect(within(own).queryByRole("button", { name: "Remove" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(1);
  });

  it("saves a renamed student", async () => {
    const api = apiForTeacher();
    mount(api, "en");
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
    const { container } = mount(api, "en");
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    const options = Array.from(
      container.querySelectorAll("#roster-group-names option"),
    ).map((option) => option.getAttribute("value"));
    expect(options).toEqual(["Team Aurora", "Team Borealis"]);
  });

  it("confirms before removing and sends the new status", async () => {
    const api = apiForTeacher();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    mount(api, "en");

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
    mount(api, "en");

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
    const { container } = mount(api, "en");

    const members = await screen.findByRole("region", { name: /Members/ });
    // Three current members are counted; the removed one is not among them.
    expect(within(members).getByText("3")).toBeTruthy();
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

  it("shows an issued password once", async () => {
    const api = apiForTeacher();
    mount(api, "en");

    fireEvent.click(await screen.findByRole("button", { name: "Reset" }));
    expect(await screen.findByText("swift-otter-42")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("swift-otter-42");
  });

  it("opens a group's workspace from its own row", async () => {
    const api = apiForTeacher();
    mount(api, "en");

    // Entering a group the caller is not in joins first, then opens it: one
    // action from the row rather than a state to set and then act on.
    const enter = await screen.findAllByRole("button", { name: "Enter" });
    fireEvent.click(enter[1]);
    await waitFor(() =>
      expect(api.joinGroupAsTeacher).toHaveBeenCalledWith("other-group"),
    );
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/student/groups/other-group"),
    );
  });

  it("joins again a group the roster still lists it in", async () => {
    const api = apiForTeacher();
    mount(api, "en");

    // The roster can load before the previous visit's leave finishes, so the
    // listing is not trusted: joining is idempotent and always comes first.
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Enter" }))[0],
    );
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(`/student/groups/${groupId}`),
    );
    expect(api.joinGroupAsTeacher).toHaveBeenCalledWith(groupId);
    expect(screen.queryByRole("button", { name: "Leave" })).toBeNull();
  });

  it("renders the Chinese copy for the same surface", async () => {
    const api = apiForTeacher();
    mount(api, "zh");
    expect(await screen.findByText("new-student")).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 1 })[0].className).toBe(
      "sr-only",
    );
    expect(screen.queryByText("自主注册", { exact: false })).toBeNull();
    expect(screen.getAllByRole("button", { name: "编辑" })).toHaveLength(1);
  });
});
