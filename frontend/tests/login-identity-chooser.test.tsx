import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  LoginForm,
  SessionProvider,
  useSession,
} from "../components/session-provider";
import {
  PlatformApi,
  PlatformApiError,
  type AuthSession,
  type LoginIdentityChoice,
} from "../lib/api";
import { LOGIN_QUEUE_STORAGE_KEY } from "../lib/login-queue";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
  usePathname: () => "/",
}));

const choice: LoginIdentityChoice = {
  choice_token: "state-only-choice-token",
  expires_in_seconds: 300,
  options: {
    classes: [
      { course_id: "class-one", code: "one", name: "Maya1001" },
      { course_id: "class-two", code: "two", name: "Maya1002" },
    ],
  },
};

function session(role: "teacher" | "student"): AuthSession {
  return {
    csrf_token: `csrf-${role}`,
    expires_at: "2026-11-12T00:00:00Z",
    user: {
      id: role === "teacher" ? "maya" : "bowen",
      username: role === "teacher" ? "maya" : "bowen",
      display_name: role === "teacher" ? "Maya" : "Bowen",
      courses: [{ course_id: "class-two", role }],
      groups: [],
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function makeApi() {
  return {
    me: vi.fn().mockRejectedValue(new PlatformApiError(401, "Sign in.")),
    login: vi.fn<PlatformApi["login"]>().mockResolvedValue(choice),
    chooseLoginIdentity: vi
      .fn<PlatformApi["chooseLoginIdentity"]>()
      .mockResolvedValue(session("teacher")),
    demoIdentities: vi.fn().mockResolvedValue([]),
    getCsrfToken: vi.fn(() => undefined),
    setCsrfToken: vi.fn(),
  };
}

function SessionProbe() {
  const { status, session: current, identityGeneration } = useSession();
  return (
    <output data-testid="session-state">
      {`${status}|${current?.user.id ?? "none"}|${current?.csrf_token ?? "none"}|${identityGeneration}`}
    </output>
  );
}

function renderLogin(api: ReturnType<typeof makeApi>) {
  return render(
    <SessionProvider api={api as unknown as PlatformApi}>
      <LoginForm />
      <SessionProbe />
    </SessionProvider>,
  );
}

async function submitCredentials() {
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: "bowen" },
  });
  const password = screen.getByLabelText("Password");
  fireEvent.change(password, { target: { value: "synthetic-password" } });
  fireEvent.submit(password.closest("form")!);
  return screen.findByRole("heading", { name: "Choose how to enter" });
}

function panel() {
  return within(screen.getByRole("region", { name: "Choose how to enter" }));
}

function mayaButton() {
  return panel().getByRole("button", { name: /^Maya Teacher/ });
}

function studentButton() {
  return panel().getByRole("button", { name: /^Student Bowen/ });
}

describe("Bowen login identity chooser", () => {
  beforeEach(() => {
    navigation.replace.mockReset();
    window.history.replaceState(null, "", "/");
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("keeps the same panel anonymous, focuses the chooser and clears the credential queue", async () => {
    const api = makeApi();
    const storageWrite = vi.spyOn(Storage.prototype, "setItem");
    api.login.mockImplementation(async (_name, _password, options) => {
      options?.onQueued?.({
        position: 1,
        retryAfterSeconds: 1,
        queueLength: 2,
        estimatedWaitSeconds: 1,
        ticket: "c013796d-d5ae-4c0a-a074-605b9b31b739",
      });
      return choice;
    });
    renderLogin(api);
    await waitFor(() =>
      expect(screen.getByTestId("session-state").textContent).toBe(
        "anonymous|none|none|1",
      ),
    );
    const originalPanel = screen.getByRole("region", { name: "Sign in" });
    const heading = await submitCredentials();
    expect(heading.closest("section")).toBe(originalPanel);
    expect(document.activeElement).toBe(heading);
    expect(heading.tabIndex).toBe(-1);
    expect(screen.queryByLabelText("Password")).toBeNull();
    expect(screen.getByTestId("session-state").textContent).toBe(
      "anonymous|none|none|1",
    );
    expect(api.chooseLoginIdentity).not.toHaveBeenCalled();
    expect(navigation.replace).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(LOGIN_QUEUE_STORAGE_KEY)).toBeNull();
    expect(storageWrite).toHaveBeenCalled();
    expect(JSON.stringify(storageWrite.mock.calls)).not.toContain(
      choice.choice_token,
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    fireEvent.keyDown(heading, { key: "Escape" });
    expect(panel()).toBeTruthy();
  });

  it("enters Maya without a course_id and commits the teacher session and CSRF", async () => {
    const api = makeApi();
    renderLogin(api);
    await submitCredentials();
    fireEvent.click(mayaButton());
    await waitFor(() =>
      expect(navigation.replace).toHaveBeenCalledWith("/teacher"),
    );
    expect(api.chooseLoginIdentity).toHaveBeenCalledExactlyOnceWith({
      choice_token: choice.choice_token,
      identity: "maya",
    });
    expect(screen.getByTestId("session-state").textContent).toMatch(
      /^authenticated\|maya\|csrf-teacher\|/,
    );
    expect(api.setCsrfToken).toHaveBeenLastCalledWith("csrf-teacher");
  });

  it("toggles classes from the response and enters the selected student class", async () => {
    const api = makeApi();
    api.chooseLoginIdentity.mockResolvedValue(session("student"));
    renderLogin(api);
    await submitCredentials();
    expect(studentButton().getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("group", { name: "Pick a class" })).toBeNull();
    fireEvent.click(studentButton());
    expect(studentButton().getAttribute("aria-expanded")).toBe("true");
    const classes = within(screen.getByRole("group", { name: "Pick a class" }));
    expect(
      classes.getAllByRole("button").map((button) => button.textContent),
    ).toEqual(["Maya1001", "Maya1002"]);
    expect(api.chooseLoginIdentity).not.toHaveBeenCalled();
    fireEvent.click(studentButton());
    expect(screen.queryByRole("group", { name: "Pick a class" })).toBeNull();
    expect(studentButton().getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(studentButton());
    fireEvent.click(screen.getByRole("button", { name: "Maya1002" }));
    await waitFor(() =>
      expect(navigation.replace).toHaveBeenCalledWith("/student"),
    );
    expect(api.chooseLoginIdentity).toHaveBeenCalledExactlyOnceWith({
      choice_token: choice.choice_token,
      identity: "student",
      course_id: "class-two",
    });
    expect(screen.getByTestId("session-state").textContent).toMatch(
      /^authenticated\|bowen\|csrf-student\|/,
    );
  });

  it.each(["teacher", "student"] as const)(
    "preserves next for the %s identity",
    async (role) => {
      window.history.replaceState(
        null,
        "",
        "/?next=%2Fstudent%3Ftab%3Dhistory",
      );
      const api = makeApi();
      api.chooseLoginIdentity.mockResolvedValue(session(role));
      renderLogin(api);
      await submitCredentials();
      if (role === "teacher") fireEvent.click(mayaButton());
      else {
        fireEvent.click(studentButton());
        fireEvent.click(screen.getByRole("button", { name: "Maya1002" }));
      }
      await waitFor(() =>
        expect(navigation.replace).toHaveBeenCalledWith("/student?tab=history"),
      );
    },
  );

  it.each(["maya", "student"] as const)(
    "disables every choice while entering %s",
    async (identity) => {
      const pending = deferred<AuthSession>();
      const api = makeApi();
      api.chooseLoginIdentity.mockReturnValue(pending.promise);
      renderLogin(api);
      await submitCredentials();
      fireEvent.click(studentButton());
      fireEvent.click(
        identity === "maya"
          ? mayaButton()
          : screen.getByRole("button", { name: "Maya1001" }),
      );
      const entering = panel().getByRole("button", { name: /Entering…/ });
      expect(entering.getAttribute("aria-busy")).toBe("true");
      for (const button of panel().getAllByRole("button")) {
        expect((button as HTMLButtonElement).disabled).toBe(true);
      }
      expect(navigation.replace).not.toHaveBeenCalled();
      await act(async () =>
        pending.resolve(session(identity === "maya" ? "teacher" : "student")),
      );
    },
  );

  it.each([
    [
      "identity_choice_invalid",
      "This sign-in choice has expired or was already used. Sign in again.",
    ],
    [
      "identity_choice_unavailable",
      "This account choice is unavailable. Sign in again.",
    ],
  ])("returns to sign in after %s", async (code, message) => {
    const api = makeApi();
    api.chooseLoginIdentity.mockRejectedValue(
      new PlatformApiError(401, "Rejected.", { code }),
    );
    const storageWrite = vi.spyOn(Storage.prototype, "setItem");
    renderLogin(api);
    await submitCredentials();
    fireEvent.click(mayaButton());
    expect((await screen.findByRole("alert")).textContent).toContain(message);
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe(
      "",
    );
    expect(
      screen.queryByRole("heading", { name: "Choose how to enter" }),
    ).toBeNull();
    expect(navigation.replace).not.toHaveBeenCalled();
    expect(JSON.stringify(storageWrite.mock.calls)).not.toContain(
      choice.choice_token,
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(window.location.href).not.toContain(choice.choice_token);
  });

  it.each([
    [
      422,
      "identity_choice_course_invalid",
      {},
      "This class is unavailable. Choose another class.",
    ],
    [
      429,
      "auth_rate_limited",
      { retry_after_seconds: 12 },
      "Too many sign-in or registration attempts. Try again in 12 seconds.",
    ],
    [
      429,
      "auth_rate_limited",
      {},
      "Too many sign-in attempts. Wait a moment and try again.",
    ],
  ])(
    "keeps choices available after %s %s",
    async (status, code, details, message) => {
      const api = makeApi();
      api.chooseLoginIdentity.mockRejectedValue(
        new PlatformApiError(status, "Rejected.", { code, details }),
      );
      renderLogin(api);
      await submitCredentials();
      fireEvent.click(studentButton());
      fireEvent.click(screen.getByRole("button", { name: "Maya1001" }));
      expect((await screen.findByRole("alert")).textContent).toContain(message);
      expect((mayaButton() as HTMLButtonElement).disabled).toBe(false);
      expect(screen.getByRole("group", { name: "Pick a class" })).toBeTruthy();
      expect(navigation.replace).not.toHaveBeenCalled();
    },
  );

  it("goes back with an empty password and requires credentials again", async () => {
    const api = makeApi();
    renderLogin(api);
    await submitCredentials();
    fireEvent.click(panel().getByRole("button", { name: "Back to sign in" }));
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe(
      "",
    );
    expect((screen.getByLabelText("Username") as HTMLInputElement).value).toBe(
      "bowen",
    );
    expect(
      screen.queryByRole("heading", { name: "Choose how to enter" }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Enter your password.",
    );
    expect(api.login).toHaveBeenCalledTimes(1);
    expect(api.chooseLoginIdentity).not.toHaveBeenCalled();
  });

  it("does not restore a choice after a remount", async () => {
    const api = makeApi();
    const view = renderLogin(api);
    await submitCredentials();
    view.unmount();
    renderLogin(api);
    expect(screen.getByLabelText("Password")).toBeTruthy();
    expect(
      screen.queryByRole("heading", { name: "Choose how to enter" }),
    ).toBeNull();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("fences a late anonymous refresh when the identity choice commits", async () => {
    const staleMe = deferred<AuthSession>();
    const api = makeApi();
    api.me.mockReturnValue(staleMe.promise);
    renderLogin(api);
    await waitFor(() => expect(api.me).toHaveBeenCalledTimes(1));
    await submitCredentials();
    expect(screen.getByTestId("session-state").textContent).toBe(
      "anonymous|none|none|0",
    );
    fireEvent.click(mayaButton());
    await waitFor(() =>
      expect(navigation.replace).toHaveBeenCalledWith("/teacher"),
    );
    await act(async () =>
      staleMe.reject(new PlatformApiError(401, "Expired.")),
    );
    expect(screen.getByTestId("session-state").textContent).toBe(
      "authenticated|maya|csrf-teacher|1",
    );
    expect(api.setCsrfToken).toHaveBeenLastCalledWith("csrf-teacher");
  });
});
