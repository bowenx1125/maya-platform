import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  pathname: "/student",
  identityGeneration: 0,
  user: {
    id: "user-a",
    display_name: "Learner",
    courses: [{ course_id: "course-1", role: "student" }],
    groups: [],
  },
  api: { classroomLive: vi.fn(), agent: vi.fn(), version: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({ ...state, logout: vi.fn() }),
}));

import { AppShell } from "../components/app-shell";
import { LocaleProvider } from "../components/locale";

class FakeSocket {
  static instances: FakeSocket[] = [];
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  close() {
    this.closed = true;
  }
  push(live: unknown) {
    this.onmessage?.({ data: JSON.stringify({ live }) });
  }
}

const liveLink = () => screen.queryByRole("link", { name: "Live" });

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  state.api.classroomLive.mockReset().mockResolvedValue(null);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("student Live badge", () => {
  it("follows server pushes instead of polling every 5 s", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const view = render(
      <LocaleProvider initialLocale="en">
        <AppShell role="student">
          <p>Content</p>
        </AppShell>
      </LocaleProvider>,
    );
    expect(FakeSocket.instances).toHaveLength(1);
    expect(FakeSocket.instances[0].url).toContain(
      "/api/v1/courses/course-1/live/events",
    );
    expect(liveLink()).toBeNull();
    act(() => FakeSocket.instances[0].push({ debate_id: "d" }));
    await waitFor(() => expect(liveLink()).not.toBeNull());
    const polls = state.api.classroomLive.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });
    expect(state.api.classroomLive.mock.calls.length).toBe(polls);
    act(() => FakeSocket.instances[0].push(null));
    await waitFor(() => expect(liveLink()).toBeNull());
    view.unmount();
    expect(FakeSocket.instances[0].closed).toBe(true);
  });

  it("falls back to a poll and reconnects when the socket drops", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="student">
          <p>Content</p>
        </AppShell>
      </LocaleProvider>,
    );
    state.api.classroomLive.mockResolvedValue({ debate_id: "d" });
    act(() => FakeSocket.instances[0].onclose?.({ code: 1006 }));
    await act(async () => {
      vi.advanceTimersByTime(5_000);
    });
    expect(FakeSocket.instances).toHaveLength(2);
    await waitFor(() => expect(liveLink()).not.toBeNull());
  });

  it("does not reconnect after the server refuses access", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="student">
          <p>Content</p>
        </AppShell>
      </LocaleProvider>,
    );
    act(() => FakeSocket.instances[0].onclose?.({ code: 4401 }));
    await act(async () => {
      vi.advanceTimersByTime(120_000);
    });
    expect(FakeSocket.instances).toHaveLength(1);
  });
});
