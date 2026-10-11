import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RegistrationOptions } from "../lib/api";
import { LocaleProvider } from "../components/locale";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

vi.mock("../components/session-provider", () => ({
  useSession: vi.fn(),
}));

import { useSession } from "../components/session-provider";
import { RegisterForm } from "../components/register-form";

const mockedUseSession = vi.mocked(useSession);
const courseId = "course-id";

function options(): RegistrationOptions {
  return {
    course_id: courseId,
    course_name: "Cultural exchange",
    groups: [
      { name: "Team Aurora", member_count: 2 },
      { name: "Team Borealis", member_count: 1 },
      { name: "星辰队", member_count: 3 },
    ],
  } as RegistrationOptions;
}

function mount(locale: "en" | "zh" = "en") {
  const api = {
    registrationOptions: vi.fn().mockResolvedValue(options()),
  };
  const register = vi.fn().mockResolvedValue({
    user: { id: "new-student-id", courses: [] },
    csrf_token: "csrf",
  });
  mockedUseSession.mockReturnValue({ api, register } as never);
  const view = render(
    <LocaleProvider initialLocale={locale}>
      <RegisterForm />
    </LocaleProvider>,
  );
  return { api, register, view };
}

/** Fill the sign-in step and advance to the group step. */
async function toGroupStep(
  username = "new-student",
  password = "correct-horse-1",
) {
  fireEvent.change(await screen.findByLabelText("Username"), {
    target: { value: username },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: password },
  });
  fireEvent.change(screen.getByLabelText("Confirm password"), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  return screen.findByLabelText("Group name");
}

describe("student self-registration form", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    replace.mockReset();
  });

  it("asks for the group on a step of its own", async () => {
    mount();
    // The group field, its suggestions and its verdict are all absent while
    // the sign-in details are being filled in, so nothing can grow under the
    // student's cursor.
    expect(await screen.findByLabelText("Username")).toBeTruthy();
    expect(screen.queryByLabelText("Group name")).toBeNull();
    expect(screen.queryByRole("option")).toBeNull();
    expect(screen.getByText(/Step 1 of 2/)).toBeTruthy();

    await toGroupStep();
    expect(screen.getByText(/Step 2 of 2/)).toBeTruthy();
    expect(screen.queryByLabelText("Username")).toBeNull();
  });

  it("goes back to the sign-in step without losing what was typed", async () => {
    mount();
    await toGroupStep();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));

    const username = (await screen.findByLabelText(
      "Username",
    )) as HTMLInputElement;
    expect(username.value).toBe("new-student");
  });

  it("suggests nothing until the student starts typing", async () => {
    const { api } = mount();
    await waitFor(() => expect(api.registrationOptions).toHaveBeenCalled());
    const group = await toGroupStep();
    fireEvent.focus(group);

    // An untouched field answers a question nobody asked: the student came
    // here to write one name, and the whole course dropped over it buries it.
    expect(screen.queryByRole("option")).toBeNull();
    expect(group.getAttribute("aria-expanded")).toBe("false");

    fireEvent.change(group, { target: { value: "team" } });
    await waitFor(() =>
      expect(
        screen.getAllByRole("option").map((option) => option.textContent),
      ).toEqual(["Team Aurora2 member(s)", "Team Borealis1 member(s)"]),
    );
  });

  it("narrows suggestions to names that contain what was typed", async () => {
    mount();
    const group = await toGroupStep();
    fireEvent.focus(group);
    // A substring, not a prefix: "aurora" still finds "Team Aurora".
    fireEvent.change(group, { target: { value: "aurora" } });

    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(1));
    expect(screen.getByRole("option").textContent).toContain("Team Aurora");
  });

  it("closes the list on Escape and reopens it on the next keystroke", async () => {
    mount();
    const group = await toGroupStep();
    fireEvent.change(group, { target: { value: "team" } });
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));

    fireEvent.keyDown(group, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("option")).toBeNull());
    expect(group.getAttribute("aria-expanded")).toBe("false");

    fireEvent.change(group, { target: { value: "team " } });
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
  });

  it("walks the list with the arrow keys and takes the highlighted name", async () => {
    mount();
    const group = (await toGroupStep()) as HTMLInputElement;
    fireEvent.change(group, { target: { value: "team" } });
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));

    fireEvent.keyDown(group, { key: "ArrowDown" });
    fireEvent.keyDown(group, { key: "ArrowDown" });
    await waitFor(() =>
      expect(group.getAttribute("aria-activedescendant")).toBe(
        screen.getAllByRole("option")[1].id,
      ),
    );

    // Enter takes the highlighted row rather than submitting the empty field
    // underneath it, which would have created a group by accident.
    fireEvent.keyDown(group, { key: "Enter" });
    await waitFor(() => expect(group.value).toBe("Team Borealis"));
    expect(screen.queryByRole("option")).toBeNull();
  });

  it("says whether a typed name joins an existing group or creates one", async () => {
    mount();
    const group = await toGroupStep();

    fireEvent.change(group, { target: { value: "  team   AURORA " } });
    expect(
      await screen.findByText(/You will join Team Aurora, which has 2/),
    ).toBeTruthy();

    fireEvent.change(group, { target: { value: "Team Unknown" } });
    expect(await screen.findByText(/you will create it/i)).toBeTruthy();
  });

  it("fills the field from a suggestion", async () => {
    mount();
    const group = (await toGroupStep()) as HTMLInputElement;
    fireEvent.change(group, { target: { value: "星" } });
    fireEvent.click(await screen.findByRole("option", { name: /星辰队/ }));
    expect(group.value).toBe("星辰队");
    expect(screen.queryByRole("option")).toBeNull();
  });

  it("registers with the chosen course and no display name", async () => {
    const { register } = mount();
    const group = await toGroupStep(" new-student ");
    fireEvent.change(group, { target: { value: "Team Aurora" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() =>
      expect(register).toHaveBeenCalledWith({
        username: "new-student",
        password: "correct-horse-1",
        group_name: "Team Aurora",
        course_id: courseId,
      }),
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/student"));
    // The new account is owed its first-visit tour.
    expect(window.localStorage.getItem("maya.tour.pending")).toBe(
      "new-student-id",
    );
    window.localStorage.removeItem("maya.tour.pending");
  });

  it("returns to the first step when the account is rejected", async () => {
    const api = {
      registrationOptions: vi.fn().mockResolvedValue(options()),
    };
    const register = vi.fn().mockRejectedValue(new Error("username taken"));
    mockedUseSession.mockReturnValue({ api, register } as never);
    render(
      <LocaleProvider initialLocale="en">
        <RegisterForm />
      </LocaleProvider>,
    );

    const group = await toGroupStep();
    fireEvent.change(group, { target: { value: "Team Aurora" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    // The username is the field the student can correct, so the form goes
    // back to it rather than leaving them on the group step.
    expect(await screen.findByLabelText("Username")).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("still submits when the options request fails", async () => {
    const api = {
      registrationOptions: vi.fn().mockRejectedValue(new Error("offline")),
    };
    const register = vi.fn().mockResolvedValue({ csrf_token: "csrf" });
    mockedUseSession.mockReturnValue({ api, register } as never);
    render(
      <LocaleProvider initialLocale="en">
        <RegisterForm />
      </LocaleProvider>,
    );

    const group = await toGroupStep("solo");
    fireEvent.change(group, { target: { value: "Brand New Group" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() =>
      expect(register).toHaveBeenCalledWith({
        username: "solo",
        password: "correct-horse-1",
        group_name: "Brand New Group",
      }),
    );
  });

  it("shows a username conflict without redirecting or losing entered fields", async () => {
    const { register } = mount();
    register.mockRejectedValue(
      Object.assign(new Error("conflict"), {
        code: "username_taken",
        status: 409,
      }),
    );
    const group = await toGroupStep("ReviewRace", "abcde");
    fireEvent.change(group, { target: { value: "Équipe" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "That username is already taken. Choose another username.",
    );
    expect((screen.getByLabelText("Username") as HTMLInputElement).value).toBe(
      "ReviewRace",
    );
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe(
      "abcde",
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it("renders the Chinese copy", async () => {
    mount("zh");
    expect(await screen.findByLabelText("用户名")).toBeTruthy();
    expect(screen.getByRole("button", { name: "下一步" })).toBeTruthy();
  });
});

describe("registration guards the password before the group step", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    replace.mockReset();
  });

  it("refuses a password shorter than the server would accept", async () => {
    mount();
    fireEvent.change(await screen.findByLabelText("Username"), {
      target: { value: "tiny" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "abc" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "abc" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    // Told here rather than after choosing a group and being bounced back.
    expect(await screen.findByText(/password is too short/i)).toBeTruthy();
    expect(screen.queryByLabelText("Group name")).toBeNull();
  });

  it("refuses two passwords that do not match", async () => {
    mount();
    fireEvent.change(await screen.findByLabelText("Username"), {
      target: { value: "mismatch" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct-horse-1" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "correct-horse-2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText(/do not match/i)).toBeTruthy();
    expect(screen.queryByLabelText("Group name")).toBeNull();
  });
});
