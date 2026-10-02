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

describe("profile avatar", () => {
  it("saves a scholar the moment it is picked", async () => {
    session.api.updateCurrentUser.mockResolvedValue(undefined);
    const onSaved = vi.fn();
    inEnglish(<AccountSettings onSaved={onSaved} />);
    expect(screen.queryByRole("button", { name: "Save" })).toBeTruthy(); // password only
    const choices = screen.getAllByRole("radio");
    fireEvent.click(choices[2]);
    await waitFor(() =>
      expect(session.api.updateCurrentUser).toHaveBeenCalledWith(
        USER_AVATAR_CHOICES[2],
      ),
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
