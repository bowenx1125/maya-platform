import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  RouteGuard,
  SessionProvider,
  useSession,
} from "../components/session-provider";
import type { AuthSession, PlatformApi } from "../lib/api";
import HomePage from "../app/page";

const navigation = vi.hoisted(() => ({
  path: "/student",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
  usePathname: () => navigation.path,
}));

afterEach(() => {
  cleanup();
  navigation.path = "/student";
});

function studentSession(): AuthSession {
  return {
    csrf_token: "csrf-student",
    expires_at: "2099-01-01T00:00:00Z",
    user: {
      id: "student-id",
      username: "student",
      display_name: "Student",
      courses: [{ course_id: "course-id", role: "student" }],
      groups: [{ group_id: "group-id", role: "member" }],
    },
  } as AuthSession;
}

function fakeApi(overrides: Partial<Record<string, unknown>> = {}) {
  let csrf: string | undefined;
  return {
    me: vi.fn(async () => studentSession()),
    logout: vi.fn(async () => undefined),
    demoIdentities: vi.fn(async () => []),
    registrationOptions: vi.fn(async () => null),
    getCsrfToken: vi.fn(() => csrf),
    setCsrfToken: vi.fn((next: string | undefined) => {
      csrf = next;
    }),
    ...overrides,
  } as unknown as PlatformApi;
}

function SignOutButton() {
  const { logout } = useSession();
  return (
    <button type="button" onClick={() => void logout()}>
      sign out
    </button>
  );
}

describe("loading while the session changes", () => {
  it("keeps the loading card, not the sign-in prompt, while signing out", async () => {
    render(
      <SessionProvider api={fakeApi()}>
        <RouteGuard role="student">
          <SignOutButton />
        </RouteGuard>
      </SessionProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "sign out" }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "sign out" })).toBeNull(),
    );
    expect(document.querySelector(".loading-card")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
  });

  it("still asks an expired session to sign in", async () => {
    render(
      <SessionProvider
        api={fakeApi({
          me: vi.fn(async () => {
            throw Object.assign(new Error("expired"), { status: 401 });
          }),
        })}
      >
        <RouteGuard role="student">
          <p>inside</p>
        </RouteGuard>
      </SessionProvider>,
    );
    expect(await screen.findByRole("link", { name: "Sign in" })).toBeTruthy();
    expect(document.querySelector(".loading-card")).toBeNull();
  });

  it("shows the loading card on the sign-in page until the session is known", async () => {
    navigation.path = "/";
    let settle: (value: AuthSession) => void = () => undefined;
    render(
      <SessionProvider
        api={fakeApi({
          me: vi.fn(
            () =>
              new Promise<AuthSession>((done) => {
                settle = done;
              }),
          ),
        })}
      >
        <HomePage />
      </SessionProvider>,
    );
    await waitFor(() =>
      expect(document.querySelector(".loading-card")).toBeTruthy(),
    );
    expect(document.querySelector(".academy-intro")).toBeNull();
    settle(studentSession());
    await waitFor(() =>
      expect(document.querySelector(".loading-card")).toBeNull(),
    );
  });
});

describe("registration group list", () => {
  it("floats in reserved space, so Create account never moves under a click", () => {
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");
    const list = css.match(/\.academy-combo-list \{[^}]*\}/)?.[0] ?? "";
    const combo = css.match(/\.academy-combo \{[^}]*\}/)?.[0] ?? "";
    expect(list).toMatch(/position:\s*absolute/);
    expect(combo).toMatch(/min-height:\s*\d+px/);
  });
});
