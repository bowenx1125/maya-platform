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
  },
  refresh: vi.fn(async () => undefined),
  user: { id: "me", display_name: "Kaikai", avatar: null as string | null },
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => session,
}));

import { AccountSettings } from "../components/account-settings";
import { HomeGuide } from "../components/home-guide";
import { LocaleProvider } from "../components/locale";
import { USER_AVATAR_CHOICES } from "../components/user-avatar";

afterEach(() => {
  cleanup();
  session.user = { id: "me", display_name: "Kaikai", avatar: null };
  vi.clearAllMocks();
});

const inEnglish = (ui: ReactNode) =>
  render(<LocaleProvider initialLocale="en">{ui}</LocaleProvider>);

describe("home guide", () => {
  it("points only the first unfinished step onward", () => {
    inEnglish(
      <HomeGuide
        steps={[
          { label: "Meet your group", complete: true, href: "/a" },
          { label: "Build an Agent", complete: false, href: "/b" },
          {
            label: "Create a voice",
            complete: false,
            href: "/c",
            optional: true,
          },
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
      <LocaleProvider initialLocale="en">
        <AccountSettings />
      </LocaleProvider>
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
      <LocaleProvider initialLocale="en">
        <AccountSettings onSaved={onSaved} />
      </LocaleProvider>
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
