import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useState } from "react";
import { SessionProvider, useSession } from "../components/session-provider";
import type { AuthSession, PlatformApi } from "../lib/api";

vi.mock("next/navigation", () => ({
  usePathname: () => "/teacher/agents",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
function auth(courses = ["a", "b"], group = ""): AuthSession {
  return {
    csrf_token: "synthetic-csrf",
    expires_at: "2099-01-01T00:00:00Z",
    user: {
      id: "teacher",
      username: "teacher",
      display_name: "Teacher",
      courses: courses.map((course_id) => ({ course_id, role: "teacher" })),
      groups: group ? [{ group_id: group, role: "member" }] : [],
    },
  };
}
function Probe() {
  const context = useSession();
  const [error, setError] = useState("");
  return (
    <>
      <output data-testid="scope">
        {context.user?.courses[0]?.course_id ?? "none"}|
        {context.identityGeneration}|
        {context.user?.groups[0]?.group_id ?? "none"}
      </output>
      <button
        onClick={() =>
          void context
            .selectTeacherCourse("b")
            .catch((cause: Error) => setError(cause.message))
        }
      >
        Choose B
      </button>
      <button onClick={() => void context.refresh()}>Refresh</button>
      <span>{error}</span>
    </>
  );
}
function mount(initial: AuthSession) {
  const api = {
    me: vi.fn().mockResolvedValue(initial),
    getCsrfToken: vi.fn(),
    setCsrfToken: vi.fn(),
    reportClientMetrics: vi.fn().mockResolvedValue(undefined),
  };
  render(
    <SessionProvider api={api as unknown as PlatformApi}>
      <Probe />
    </SessionProvider>,
  );
  return api;
}
afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.restoreAllMocks();
});
it("keeps the chosen class across refresh without changing the server membership list", async () => {
  const initial = auth();
  mount(initial);
  await waitFor(() =>
    expect(screen.getByTestId("scope").textContent).toBe("a|1|none"),
  );
  fireEvent.click(screen.getByText("Choose B"));
  await waitFor(() =>
    expect(screen.getByTestId("scope").textContent).toBe("b|2|none"),
  );
  fireEvent.click(screen.getByText("Refresh"));
  await waitFor(() =>
    expect(screen.getByTestId("scope").textContent).toBe("b|2|none"),
  );
  expect(initial.user.courses[0].course_id).toBe("a");
});
it("rejects a class outside the current teacher memberships", async () => {
  mount(auth(["a"]));
  await waitFor(() =>
    expect(screen.getByTestId("scope").textContent).toBe("a|1|none"),
  );
  fireEvent.click(screen.getByText("Choose B"));
  expect(await screen.findByText("This class is unavailable.")).toBeTruthy();
  expect(screen.getByTestId("scope").textContent).toBe("a|1|none");
});
it("falls back when the selected class has been revoked", async () => {
  const api = mount(auth());
  await waitFor(() =>
    expect(screen.getByTestId("scope").textContent).toBe("a|1|none"),
  );
  fireEvent.click(screen.getByText("Choose B"));
  await waitFor(() =>
    expect(screen.getByTestId("scope").textContent).toBe("b|2|none"),
  );
  api.me.mockResolvedValue(auth(["a"]));
  fireEvent.click(screen.getByText("Refresh"));
  await waitFor(() =>
    expect(screen.getByTestId("scope").textContent).toBe("a|3|none"),
  );
});
it("changes the cache identity when a student's group changes", async () => {
  const initial = auth(["a"], "old-group");
  initial.user.courses[0].role = "student";
  const api = mount(initial);
  await waitFor(() =>
    expect(screen.getByTestId("scope").textContent).toBe("a|1|old-group"),
  );
  api.me.mockResolvedValue({
    ...initial,
    user: {
      ...initial.user,
      groups: [{ group_id: "new-group", role: "member" }],
    },
  });
  fireEvent.click(screen.getByText("Refresh"));
  await waitFor(() =>
    expect(screen.getByTestId("scope").textContent).toBe("a|2|new-group"),
  );
});
