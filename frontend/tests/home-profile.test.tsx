import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  api: {
    updateCurrentUser: vi.fn(),
    changePassword: vi.fn(),
    registrationOptions: vi.fn(),
    group: vi.fn(),
  },
  refresh: vi.fn(async () => undefined),
  user: {
    id: "me",
    display_name: "Kaikai",
    avatar: null as string | null,
  } as {
    id: string;
    display_name: string;
    avatar: string | null;
    courses?: { course_id: string; role: string }[];
    groups?: { group_id: string; role: string }[];
    username?: string;
  },
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => session,
}));

import { AccountSettings } from "../components/account-settings";
import { PlatformApiError } from "../lib/api/platform";
import { HomeGuide } from "../components/home-guide";
import { courseChatCount } from "../components/student-workspace";
import type { ConversationSession } from "../lib/api";
import { USER_AVATAR_CHOICES } from "../components/user-avatar";

afterEach(() => {
  cleanup();
  session.user = { id: "me", display_name: "Kaikai", avatar: null };
  vi.clearAllMocks();
});

const inEnglish = (ui: ReactNode) => render(<>{ui}</>);

describe("home guide", () => {
  it("points only the first unfinished step onward", () => {
    inEnglish(
      <HomeGuide
        steps={[
          { label: "Meet your group", complete: true, href: "/a" },
          { label: "Build an Agent", complete: false, href: "/b" },
          { label: "Create a voice", complete: false, href: "/c" },
        ]}
      />,
    );
    const next = screen.getByRole("link", { name: /Build an Agent/ });
    expect(next.getAttribute("aria-current")).toBe("step");
    expect(
      screen
        .getByRole("link", { name: /Meet your group/ })
        .getAttribute("aria-current"),
    ).toBeNull();
    // A finished step still says so to a screen reader, without a check mark.
    expect(
      screen.getByRole("link", { name: /Meet your group.*Done/ }),
    ).toBeTruthy();
    expect(document.querySelectorAll(".home-guide-state")).toHaveLength(1);
    expect(document.body.textContent).not.toContain("✓");
  });
});

describe("course chat count", () => {
  it("counts only chats in the current course", () => {
    const chats = [
      { id: "a", agent: { course_id: "c1" } },
      { id: "b", agent: { course_id: "c2" } },
      { id: "t", team: { course_id: "c1" } },
      { id: "u", team: { course_id: "c3" } },
    ] as unknown as ConversationSession[];
    expect(courseChatCount(chats, "c1")).toBe(2);
    expect(courseChatCount(chats, "c9")).toBe(0);
    expect(courseChatCount(chats, undefined)).toBe(0);
  });
});

describe("profile name", () => {
  it("offers Save only for a new name, and sends it collapsed", async () => {
    session.api.updateCurrentUser.mockResolvedValue(undefined);
    const onSaved = vi.fn();
    inEnglish(<AccountSettings onSaved={onSaved} />);
    const input = screen.getByLabelText("Display name") as HTMLInputElement;
    expect(input.value).toBe("Kaikai");
    // Only the password's Save until the name changes.
    expect(screen.getAllByRole("button", { name: "Save" })).toHaveLength(1);

    fireEvent.change(input, { target: { value: "Kaikai  " } });
    expect(screen.getAllByRole("button", { name: "Save" })).toHaveLength(1);

    fireEvent.change(input, { target: { value: "  Kai   Kai " } });
    const saves = screen.getAllByRole("button", { name: "Save" });
    expect(saves).toHaveLength(2);
    fireEvent.click(saves[0]);
    await waitFor(() =>
      expect(session.api.updateCurrentUser).toHaveBeenCalledWith({
        display_name: "Kai Kai",
      }),
    );
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(session.refresh).toHaveBeenCalled();
  });
});

describe("profile group", () => {
  const student = {
    id: "me",
    display_name: "Kaikai",
    avatar: null,
    courses: [{ course_id: "course", role: "student" }],
    groups: [{ group_id: "aurora-id", role: "member" }],
  };

  it("offers a student the course's groups and warns before moving", async () => {
    session.user = student;
    session.api.registrationOptions.mockResolvedValue({
      course_id: "course",
      course_name: "Cultural exchange",
      groups: [
        { name: "Aurora", member_count: 2 },
        { name: "Borealis", member_count: 1 },
      ],
    });
    session.api.group.mockResolvedValue({ id: "aurora-id", name: "Aurora" });
    session.api.updateCurrentUser.mockResolvedValue(undefined);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const onSaved = vi.fn();
    inEnglish(<AccountSettings onSaved={onSaved} />);

    const picker = (await screen.findByLabelText("Group")) as HTMLSelectElement;
    await waitFor(() => expect(picker.value).toBe("Aurora"));
    expect([...picker.options].map((option) => option.value)).toEqual([
      "Aurora",
      "Borealis",
    ]);
    expect(screen.getAllByRole("button", { name: "Save" })).toHaveLength(1);

    fireEvent.change(picker, { target: { value: "Borealis" } });
    const save = screen.getAllByRole("button", { name: "Save" })[0];
    // Declining the warning keeps the student where they are.
    fireEvent.click(save);
    expect(confirm.mock.calls[0][0]).toContain("stay in Aurora");
    expect(session.api.updateCurrentUser).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    fireEvent.click(save);
    await waitFor(() =>
      expect(session.api.updateCurrentUser).toHaveBeenCalledWith({
        group_name: "Borealis",
      }),
    );
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(session.refresh).toHaveBeenCalled();
    // The home reloads from the new session; its own reload still points at
    // the group this student just left.
    expect(onSaved).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("gives a teacher no group picker", async () => {
    session.user = {
      ...student,
      courses: [{ course_id: "course", role: "teacher" }],
    };
    inEnglish(<AccountSettings />);
    await screen.findByLabelText("Display name");
    expect(screen.queryByLabelText("Group")).toBeNull();
    expect(session.api.registrationOptions).not.toHaveBeenCalled();
  });

  it("offers Bowen the groups of the class he entered, not the other class", async () => {
    session.user = {
      ...student,
      username: "bowen",
      courses: [
        { course_id: "maya1001", role: "student" },
        { course_id: "maya1002", role: "student" },
      ],
      groups: [
        { group_id: "shell", role: "member" },
        { group_id: "team", role: "member" },
        { group_id: "other", role: "member" },
      ],
    };
    session.api.registrationOptions.mockResolvedValue({
      course_id: "maya1002",
      course_name: "Maya1002",
      groups: [{ name: "Demo Group", member_count: 5 }],
      classes: [
        {
          course_id: "maya1002",
          course_name: "Maya1002",
          groups: [
            { name: "Demo Group", member_count: 5 },
            { name: "Students", member_count: 1 },
          ],
        },
        {
          course_id: "maya1001",
          course_name: "Maya1001",
          groups: [
            { name: "First Team", member_count: 3 },
            { name: "Students", member_count: 2 },
          ],
        },
      ],
    });
    session.api.group.mockImplementation(async (groupId: string) => {
      if (groupId === "team")
        return { id: "team", name: "First Team", course_id: "maya1001" };
      if (groupId === "other")
        return { id: "other", name: "Students", course_id: "maya1002" };
      return { id: "shell", name: "Students", course_id: "maya1001" };
    });
    inEnglish(<AccountSettings />);
    const picker = (await screen.findByLabelText("Group")) as HTMLSelectElement;
    await waitFor(() => expect(picker.value).toBe("First Team"));
    expect([...picker.options].map((option) => option.value)).toEqual([
      "First Team",
      "Students",
    ]);
  });
});

describe("profile class", () => {
  it("confirms the move and refreshes the session with the selected class", async () => {
    session.user = {
      id: "me",
      display_name: "Kaikai",
      avatar: null,
      courses: [{ course_id: "first", role: "student" }],
    };
    session.api.registrationOptions.mockResolvedValue({
      course_id: "first",
      groups: [],
      classes: [
        { course_id: "first", course_name: "Maya1001" },
        { course_id: "second", course_name: "Maya1002" },
      ],
    });
    session.api.updateCurrentUser.mockResolvedValue(undefined);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    try {
      inEnglish(<AccountSettings />);
      const picker = (await screen.findByLabelText(
        "Class",
      )) as HTMLSelectElement;
      expect(picker.value).toBe("first");
      fireEvent.change(picker, { target: { value: "second" } });
      const save = screen.getAllByRole("button", { name: "Save" })[0];
      fireEvent.click(save);
      expect(confirm).toHaveBeenCalledWith(
        "Change class? Your existing work stays in the previous class.",
      );
      expect(session.api.updateCurrentUser).not.toHaveBeenCalled();
      confirm.mockReturnValue(true);
      fireEvent.click(save);
      await waitFor(() =>
        expect(session.api.updateCurrentUser).toHaveBeenCalledWith({
          course_id: "second",
        }),
      );
      await waitFor(() => expect(session.refresh).toHaveBeenCalled());
    } finally {
      confirm.mockRestore();
    }
  });

  it("does not offer teachers a class change", () => {
    session.user = {
      id: "teacher",
      display_name: "Maya",
      avatar: null,
      courses: [{ course_id: "first", role: "teacher" }],
    };
    inEnglish(<AccountSettings />);
    expect(screen.queryByLabelText("Class")).toBeNull();
    expect(session.api.registrationOptions).not.toHaveBeenCalled();
  });
});

describe("profile avatar", () => {
  it("saves a scholar the moment it is picked", async () => {
    session.api.updateCurrentUser.mockResolvedValue(undefined);
    const onSaved = vi.fn();
    inEnglish(<AccountSettings onSaved={onSaved} />);
    expect(screen.queryByRole("button", { name: "Save" })).toBeTruthy(); // password only
    const choices = screen.getAllByRole("radio");
    fireEvent.click(choices[2]);
    await waitFor(() =>
      expect(session.api.updateCurrentUser).toHaveBeenCalledWith({
        avatar: USER_AVATAR_CHOICES[2],
      }),
    );
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect((choices[2] as HTMLInputElement).checked).toBe(true);
    expect(screen.getAllByRole("button", { name: "Save" })).toHaveLength(1);
  });

  it("puts the old face back when the server refuses the new one", async () => {
    session.api.updateCurrentUser.mockRejectedValue(new Error("nope"));
    inEnglish(<AccountSettings />);
    const choices = screen.getAllByRole("radio");
    fireEvent.click(choices[1]);
    expect(await screen.findByRole("alert")).toBeTruthy();
    await waitFor(() =>
      expect((choices[1] as HTMLInputElement).checked).toBe(false),
    );
  });
});

describe("profile identity boundary", () => {
  it("resets the avatar and password draft when the current account changes", () => {
    session.user = {
      id: "a",
      display_name: "A",
      avatar: USER_AVATAR_CHOICES[0],
    };
    const content = () => (
      <>
        <AccountSettings />
      </>
    );
    const view = render(content());
    fireEvent.change(screen.getByLabelText("Current password"), {
      target: { value: "old-password" },
    });
    session.user = {
      id: "b",
      display_name: "B",
      avatar: USER_AVATAR_CHOICES[1],
    };
    view.rerender(content());
    expect((screen.getAllByRole("radio")[1] as HTMLInputElement).checked).toBe(
      true,
    );
    expect(
      (screen.getByLabelText("Current password") as HTMLInputElement).value,
    ).toBe("");
  });

  it("ignores a previous account's late avatar response", async () => {
    let finish!: () => void;
    session.api.updateCurrentUser.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const onSaved = vi.fn();
    const content = () => (
      <>
        <AccountSettings onSaved={onSaved} />
      </>
    );
    const view = render(content());
    fireEvent.click(screen.getAllByRole("radio")[2]);
    session.user = {
      id: "b",
      display_name: "B",
      avatar: USER_AVATAR_CHOICES[1],
    };
    view.rerender(content());
    finish();
    await waitFor(() =>
      expect(
        (screen.getAllByRole("radio")[1] as HTMLInputElement).checked,
      ).toBe(true),
    );
    expect(session.refresh).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("profile password (U3)", () => {
  it("numbers the confirm field and its error line on a mismatch", async () => {
    inEnglish(<AccountSettings />);
    fireEvent.change(screen.getByLabelText("Current password"), {
      target: { value: "old-password" },
    });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "new-password-1" },
    });
    const confirm = screen.getByLabelText("Confirm password");
    expect(confirm.getAttribute("aria-invalid")).toBeNull();
    fireEvent.change(confirm, { target: { value: "new-password-2" } });
    fireEvent.submit(confirm.closest("form")!);

    const line = await screen.findByRole("alert");
    expect(line.textContent).toMatch(/do not match/i);
    expect(
      line.querySelector('[data-sticker="field"]')?.getAttribute("data-n"),
    ).toBe("1");
    expect(confirm.getAttribute("aria-invalid")).toBe("true");
    expect(confirm.getAttribute("aria-describedby")).toBe(line.id);
    expect(session.api.changePassword).not.toHaveBeenCalled();
  });

  it("numbers the current password field when it is wrong, not the server !", async () => {
    session.api.changePassword.mockRejectedValueOnce(
      new PlatformApiError(401, "password_incorrect", {
        code: "password_incorrect",
        message: "That password does not match this account.",
      }),
    );
    inEnglish(<AccountSettings />);
    const current = screen.getByLabelText("Current password");
    fireEvent.change(current, { target: { value: "wrong-password" } });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "new-password-1" },
    });
    const confirm = screen.getByLabelText("Confirm password");
    fireEvent.change(confirm, { target: { value: "new-password-1" } });
    fireEvent.submit(confirm.closest("form")!);

    const line = await screen.findByRole("alert");
    expect(
      line.querySelector('[data-sticker="field"]')?.getAttribute("data-n"),
    ).toBe("1");
    expect(line.querySelector('[data-sticker="server"]')).toBeNull();
    expect(current.getAttribute("aria-invalid")).toBe("true");
    expect(confirm.getAttribute("aria-invalid")).toBeNull();
  });
});
