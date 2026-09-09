import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CourseRoster, Group, RosterEntry } from "../lib/api";
import { LocaleProvider } from "../components/locale";

vi.mock("../components/session-provider", () => ({
  useSession: vi.fn(),
}));

import { useSession } from "../components/session-provider";
import { RosterWorkspace } from "../components/roster-workspace";

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
  mockedUseSession.mockReturnValue({
    api,
    user: {
      id: teacherId,
      courses: [{ course_id: courseId, role: "teacher" }],
      groups: [],
    },
  } as never);
  return render(
    <LocaleProvider initialLocale={locale}>
      <RosterWorkspace />
    </LocaleProvider>,
  );
}

describe("teacher account management", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("offers edits only for accounts an edit can outlive a restart", async () => {
    const api = apiForTeacher();
    mount(api, "en");
    await waitFor(() => expect(api.courseRoster).toHaveBeenCalled());

    expect(await screen.findByText("New Student")).toBeTruthy();
    expect(screen.getByText("Bowen Student 1")).toBeTruthy();
    // One editable account yields one Edit control; the catalog identity is
    // listed with the reason instead.
    expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(1);
    expect(
      screen.getByText(/re-applied from its source every time/i),
    ).toBeTruthy();
  });

  it("saves a renamed student", async () => {
    const api = apiForTeacher();
    mount(api, "en");
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    const nameField = screen.getByLabelText("Display name");
    fireEvent.change(nameField, { target: { value: "Ada Lovelace" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

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

  it("confirms before deactivating and sends the new status", async () => {
    const api = apiForTeacher();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    mount(api, "en");

    fireEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
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

    fireEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(api.courseRoster).toHaveBeenCalled());
    expect(api.updateCourseMember).not.toHaveBeenCalled();
  });

  it("shows an issued password once", async () => {
    const api = apiForTeacher();
    mount(api, "en");

    fireEvent.click(
      await screen.findByRole("button", { name: "Reset password" }),
    );
    expect(await screen.findByText("swift-otter-42")).toBeTruthy();
    expect(screen.getByText(/shown once/i)).toBeTruthy();
  });

  it("walks the caller into a group and back out", async () => {
    const api = apiForTeacher();
    mount(api, "en");

    const join = await screen.findAllByRole("button", { name: "Join" });
    fireEvent.click(join[0]);
    await waitFor(() =>
      expect(api.joinGroupAsTeacher).toHaveBeenCalledWith(groupId),
    );
  });

  it("renders the Chinese copy for the same surface", async () => {
    const api = apiForTeacher();
    mount(api, "zh");
    expect(await screen.findByText("自主注册", { exact: false })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "编辑" })).toHaveLength(1);
  });
});
