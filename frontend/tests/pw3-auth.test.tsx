import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LoginForm, SessionProvider } from "../components/session-provider";
import { LocaleProvider } from "../components/locale";
import { PlatformApi, PlatformApiError, type AuthSession } from "../lib/api";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
  usePathname: () => "/login",
}));

function studentSession(): AuthSession {
  return {
    csrf_token: "csrf-student",
    expires_at: "2026-08-28T12:00:00Z",
    user: {
      id: "student-id",
      username: "student-private",
      display_name: "Student",
      courses: [{ course_id: "course-id", role: "student" }],
      groups: [{ group_id: "group-id", role: "member" }],
    },
  };
}

describe("PW3-A anonymous Demo login", () => {
  it("loads safe identity cards without a cookie and quick-logs in", async () => {
    const quickLogin = vi.fn(async () => studentSession());
    const api = {
      me: vi.fn(async () => {
        throw new PlatformApiError(401, "Authentication is required.");
      }),
      demoIdentities: vi.fn(async () => [
        {
          user_id: "student-id",
          display_name: "Student",
          role: "student" as const,
        },
      ]),
      quickLogin,
      getCsrfToken: vi.fn(() => "csrf-student"),
    } as unknown as PlatformApi;

    render(
      <LocaleProvider initialLocale="en">
        <SessionProvider api={api}>
          <LoginForm />
        </SessionProvider>
      </LocaleProvider>,
    );

    const card = await screen.findByRole("button", { name: /Student/ });
    expect(screen.getByText("Use username and password instead")).toBeTruthy();
    const fallbackDetails = screen
      .getByText("Use username and password instead")
      .closest("details") as HTMLDetailsElement;
    expect(fallbackDetails.open).toBe(false);
    fireEvent.click(card);

    await waitFor(() => expect(quickLogin).toHaveBeenCalledWith("student-id"));
    expect(navigation.replace).toHaveBeenCalledWith("/student");
  });
});
