import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  LoginForm,
  RouteGuard,
  SessionProvider,
  useSession,
} from "../components/session-provider";
import { LocaleProvider } from "../components/locale";
import { PlatformApi, PlatformApiError, type AuthSession } from "../lib/api";
import { sanitizeNextPath } from "../lib/navigation";
import HomePage from "../app/page";

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
  beforeEach(() => navigation.replace.mockReset());

  afterEach(() => cleanup());

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
    expect(screen.getByLabelText("Username")).toBeTruthy();
    expect(screen.getByLabelText("Password")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByText("Use username and password instead")).toBeNull();
    fireEvent.click(card);

    await waitFor(() => expect(quickLogin).toHaveBeenCalledWith("student-id"));
    expect(navigation.replace).toHaveBeenCalledWith("/student");
  });

  it("keeps the home page focused on Maya and both login paths", async () => {
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
      getCsrfToken: vi.fn(() => null),
    } as unknown as PlatformApi;

    render(
      <LocaleProvider initialLocale="en">
        <SessionProvider api={api}>
          <HomePage />
        </SessionProvider>
      </LocaleProvider>,
    );

    expect(
      screen.getByRole("heading", {
        name: "Mayaform",
      }),
    ).toBeTruthy();
    expect(await screen.findByRole("button", { name: /Student/ })).toBeTruthy();
    expect(screen.getByLabelText("Username")).toBeTruthy();
    expect(screen.getByLabelText("Password")).toBeTruthy();
    expect(
      screen.queryByRole("link", { name: "Environment health" }),
    ).toBeNull();
    expect(screen.queryByText("Build with intention")).toBeNull();
    expect(screen.queryByText("Release with context")).toBeNull();
    expect(screen.queryByText("Keep the boundary clear")).toBeNull();
    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
    expect(screen.queryByText(/WAVE 1A/)).toBeNull();
  });

  it("keeps password login usable when the Demo identity catalog is unavailable", async () => {
    const login = vi.fn(async () => studentSession());
    const api = {
      me: vi.fn(async () => {
        throw new PlatformApiError(401, "Authentication is required.");
      }),
      demoIdentities: vi.fn(async () => {
        throw new PlatformApiError(404, "Not found.");
      }),
      login,
      getCsrfToken: vi.fn(() => undefined),
    } as unknown as PlatformApi;

    render(
      <LocaleProvider initialLocale="en">
        <SessionProvider api={api}>
          <LoginForm />
        </SessionProvider>
      </LocaleProvider>,
    );

    await waitFor(() => expect(api.demoIdentities).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Demo identity")).toBeNull();
    expect(screen.queryByText("or")).toBeNull();
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
    const username = screen.getByLabelText("Username");
    const password = screen.getByLabelText("Password");
    fireEvent.change(username, { target: { value: "student" } });
    fireEvent.change(password, { target: { value: "secret" } });
    fireEvent.submit(password.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(login).toHaveBeenCalledWith(
        "student",
        "secret",
        expect.objectContaining({
          signal: expect.any(AbortSignal),
          onQueued: expect.any(Function),
        }),
      ),
    );
    expect(navigation.replace).toHaveBeenCalledWith("/student");
  });
});

describe("PW3-A post-login next target", () => {
  it("returns only a same-origin pathname, search and hash", () => {
    expect(sanitizeNextPath("/teacher?tab=history#reports")).toBe(
      "/teacher?tab=history#reports",
    );
    expect(sanitizeNextPath(decodeURIComponent("/%5Cevil"))).toBeNull();
    expect(sanitizeNextPath("/%5Cevil")).toBeNull();
    expect(sanitizeNextPath("//evil.example/teacher")).toBeNull();
    expect(sanitizeNextPath("/teacher\u0000")).toBeNull();
    expect(sanitizeNextPath("https://evil.example/teacher")).toBeNull();
    expect(
      sanitizeNextPath(`${window.location.origin}/teacher?tab=history#reports`),
    ).toBe("/teacher?tab=history#reports");
  });
});

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function teacherSession(csrfToken = "csrf-teacher"): AuthSession {
  return {
    csrf_token: csrfToken,
    expires_at: "2026-08-28T12:00:00Z",
    user: {
      id: "teacher-id",
      username: "teacher-private",
      display_name: "Teacher",
      courses: [{ course_id: "course-id", role: "teacher" }],
      groups: [],
    },
  };
}

function SessionRaceProbe() {
  const { api, status, session, login, quickLogin, switchIdentity, logout } =
    useSession();
  return (
    <>
      <output data-testid="session-race-state">
        {`${status}|${session?.user.id ?? "none"}|${api.getCsrfToken() ?? "none"}`}
      </output>
      <button
        type="button"
        onClick={() => void login("user", "password").catch(() => undefined)}
      >
        start login
      </button>
      <button
        type="button"
        onClick={() => void quickLogin("student-id").catch(() => undefined)}
      >
        start quick login
      </button>
      <button
        type="button"
        onClick={() => void switchIdentity("teacher-id").catch(() => undefined)}
      >
        start switch
      </button>
      <button
        type="button"
        onClick={() => void logout().catch(() => undefined)}
      >
        start logout
      </button>
    </>
  );
}

function renderRaceProbe(api: PlatformApi) {
  return render(
    <SessionProvider api={api}>
      <SessionRaceProbe />
    </SessionProvider>,
  );
}

describe("teacher group visit", () => {
  afterEach(() => cleanup());

  function teacherSession(groups: AuthSession["user"]["groups"]): AuthSession {
    return {
      csrf_token: "csrf-teacher",
      expires_at: "2026-08-28T12:00:00Z",
      user: {
        id: "teacher-id",
        username: "maya",
        display_name: "Maya",
        courses: [{ course_id: "course-id", role: "teacher" }],
        groups,
      },
    };
  }

  it("loads the joined group before refusing the student workspace", async () => {
    const joined = teacherSession([{ group_id: "group-id", role: "member" }]);
    const api = {
      me: vi
        .fn()
        .mockResolvedValueOnce(teacherSession([]))
        .mockResolvedValue(joined),
      getCsrfToken: vi.fn(() => "csrf-teacher"),
    } as unknown as PlatformApi;

    render(
      <LocaleProvider initialLocale="en">
        <SessionProvider api={api}>
          <RouteGuard role="student">
            <p>Group workspace</p>
          </RouteGuard>
        </SessionProvider>
      </LocaleProvider>,
    );

    expect(await screen.findByText("Group workspace")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(api.me).toHaveBeenCalledTimes(2);
  });

  it("shows the account boundary when the teacher still has no group", async () => {
    const api = {
      me: vi.fn(async () => teacherSession([])),
      getCsrfToken: vi.fn(() => "csrf-teacher"),
    } as unknown as PlatformApi;

    render(
      <LocaleProvider initialLocale="en">
        <SessionProvider api={api}>
          <RouteGuard role="student">
            <p>Group workspace</p>
          </RouteGuard>
        </SessionProvider>
      </LocaleProvider>,
    );

    expect(
      await screen.findByRole("heading", {
        name: "That view is not available for this account.",
      }),
    ).toBeTruthy();
    expect(screen.queryByText("Group workspace")).toBeNull();
  });
});

describe("PW3-A SessionProvider operation fences", () => {
  afterEach(() => cleanup());

  it("does not let a late /me 401 clear a newer login or CSRF token", async () => {
    const me = deferred<AuthSession>();
    const login = deferred<AuthSession>();
    let csrfToken: string | undefined = "csrf-initial";
    const api = {
      me: vi.fn(() =>
        me.promise.then((next) => {
          csrfToken = next.csrf_token;
          return next;
        }),
      ),
      login: vi.fn(() =>
        login.promise.then((next) => {
          csrfToken = next.csrf_token;
          return next;
        }),
      ),
      quickLogin: vi.fn(async () => studentSession()),
      switchDemoIdentity: vi.fn(async () => teacherSession()),
      logout: vi.fn(async () => undefined),
      demoIdentities: vi.fn(async () => []),
      getCsrfToken: vi.fn(() => csrfToken),
      setCsrfToken: vi.fn((next: string | undefined) => {
        csrfToken = next;
      }),
    } as unknown as PlatformApi;

    renderRaceProbe(api);
    await waitFor(() => expect(api.me).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "start login" }));
    login.resolve(teacherSession());

    await waitFor(() =>
      expect(screen.getByTestId("session-race-state").textContent).toBe(
        "authenticated|teacher-id|csrf-teacher",
      ),
    );
    me.reject(new PlatformApiError(401, "Authentication is required."));

    await waitFor(() =>
      expect(api.setCsrfToken).toHaveBeenLastCalledWith("csrf-teacher"),
    );
    expect(screen.getByTestId("session-race-state").textContent).toBe(
      "authenticated|teacher-id|csrf-teacher",
    );
  });

  it("queues quick login behind a password login and leaves the last token", async () => {
    const login = deferred<AuthSession>();
    const quickLogin = deferred<AuthSession>();
    let csrfToken: string | undefined;
    const api = {
      me: vi.fn(async () => {
        throw new PlatformApiError(401, "Authentication is required.");
      }),
      login: vi.fn(() =>
        login.promise.then((next) => {
          csrfToken = next.csrf_token;
          return next;
        }),
      ),
      quickLogin: vi.fn(() =>
        quickLogin.promise.then((next) => {
          csrfToken = next.csrf_token;
          return next;
        }),
      ),
      switchDemoIdentity: vi.fn(async () => teacherSession()),
      logout: vi.fn(async () => undefined),
      demoIdentities: vi.fn(async () => []),
      getCsrfToken: vi.fn(() => csrfToken),
      setCsrfToken: vi.fn((next: string | undefined) => {
        csrfToken = next;
      }),
    } as unknown as PlatformApi;

    renderRaceProbe(api);
    await waitFor(() =>
      expect(screen.getByTestId("session-race-state").textContent).toBe(
        "anonymous|none|none",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "start login" }));
    fireEvent.click(screen.getByRole("button", { name: "start quick login" }));
    await waitFor(() => expect(api.login).toHaveBeenCalledTimes(1));
    expect(api.quickLogin).not.toHaveBeenCalled();
    login.resolve(teacherSession());

    await waitFor(() => expect(api.quickLogin).toHaveBeenCalledTimes(1));
    quickLogin.resolve(studentSession());

    await waitFor(() =>
      expect(screen.getByTestId("session-race-state").textContent).toBe(
        "authenticated|student-id|csrf-student",
      ),
    );
    expect(screen.getByTestId("session-race-state").textContent).toBe(
      "authenticated|student-id|csrf-student",
    );
  });

  it("serializes switch then logout and leaves the final session anonymous", async () => {
    const switchIdentity = deferred<AuthSession>();
    const logout = deferred<void>();
    let csrfToken: string | undefined;
    const api = {
      me: vi.fn(async () => teacherSession("csrf-current")),
      login: vi.fn(async () => teacherSession()),
      quickLogin: vi.fn(async () => studentSession()),
      switchDemoIdentity: vi.fn(() =>
        switchIdentity.promise.then((next) => {
          csrfToken = next.csrf_token;
          return next;
        }),
      ),
      logout: vi.fn(() =>
        logout.promise.then(() => {
          csrfToken = undefined;
        }),
      ),
      demoIdentities: vi.fn(async () => []),
      getCsrfToken: vi.fn(() => csrfToken),
      setCsrfToken: vi.fn((next: string | undefined) => {
        csrfToken = next;
      }),
    } as unknown as PlatformApi;

    renderRaceProbe(api);
    await waitFor(() =>
      expect(screen.getByTestId("session-race-state").textContent).toBe(
        "authenticated|teacher-id|csrf-current",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "start switch" }));
    fireEvent.click(screen.getByRole("button", { name: "start logout" }));
    await waitFor(() =>
      expect(api.switchDemoIdentity).toHaveBeenCalledTimes(1),
    );
    expect(api.logout).not.toHaveBeenCalled();
    switchIdentity.resolve(studentSession());

    await waitFor(() => expect(api.logout).toHaveBeenCalledTimes(1));
    logout.resolve();

    await waitFor(() =>
      expect(api.setCsrfToken).toHaveBeenLastCalledWith(undefined),
    );
    expect(screen.getByTestId("session-race-state").textContent).toBe(
      "anonymous|none|none",
    );
  });
});
