import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ClassroomLive } from "../components/classroom-live";
import { LocaleProvider } from "../components/locale";
import {
  PlatformApiError,
  type LiveSnapshot,
  type LiveSummary,
} from "../lib/api";

const session = vi.hoisted(() => ({
  user: { courses: [{ course_id: "course-a" }] },
  api: {
    classroomLive: vi.fn<(courseId: string) => Promise<LiveSummary | null>>(),
    liveSnapshot: vi.fn<(debateId: string) => Promise<LiveSnapshot>>(),
    updateClassroomLive: vi.fn(),
    startDebate: vi.fn(),
    nextDebate: vi.fn(),
  },
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => session,
}));
vi.mock("../components/stage3d/scholar-scene", () => ({
  ScholarScene: () => <div>Classroom scene</div>,
}));

class LiveSocket {
  static instances: LiveSocket[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  close = vi.fn();
  send = vi.fn();

  constructor(readonly url: string) {
    LiveSocket.instances.push(this);
  }

  receive(snapshot: LiveSnapshot) {
    this.onmessage?.(
      new MessageEvent("message", { data: JSON.stringify(snapshot) }),
    );
  }

  disconnect(code = 1006) {
    this.onclose?.(new CloseEvent("close", { code }));
  }
}

function summary(debateId = "debate-a", courseId = "course-a"): LiveSummary {
  return {
    debate_id: debateId,
    course_id: courseId,
    topic: "Acceptance topic",
  };
}

function snapshot(
  debateId = "debate-a",
  sequence = 1,
  speech = "Published classroom speech",
  active = true,
  interactionUrl: string | null = null,
): LiveSnapshot {
  return {
    active,
    debate_id: debateId,
    interaction_url: interactionUrl,
    sequence,
    server_time: "2026-10-12T00:00:00Z",
    participants: [
      {
        id: "participant-a",
        name: "Classroom Agent",
        avatar_config: {
          template_id: "wave1-default-head",
          material_theme: "demo",
          eye_color: null,
          default_expression: "neutral",
          expression_strength: "medium",
          motion_style: "calm",
        },
      },
    ],
    playback: null,
    turns: active
      ? [
          {
            id: "turn-a",
            participant_id: "participant-a",
            round_no: 1,
            turn_index: 0,
            speech,
            audio_url: null,
          },
        ]
      : [],
  };
}

function playingSnapshot(): LiveSnapshot {
  const playing = snapshot();
  playing.turns[0].audio_url = "/api/v1/live/debate-a/audio/turn-a";
  playing.playback = {
    status: "playing",
    mode: "live",
    current_turn_id: "turn-a",
    cursor_ms: 0,
    control_version: 1,
    next_turn_ready: false,
  };
  return playing;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function livePage(locale: "en" | "zh" = "en") {
  return (
    <LocaleProvider initialLocale={locale}>
      <ClassroomLive />
    </LocaleProvider>
  );
}

async function settle() {
  await act(async () => {});
}

async function poll() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  LiveSocket.instances = [];
  vi.stubGlobal("WebSocket", LiveSocket);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  session.user.courses = [{ course_id: "course-a" }];
  session.api.classroomLive.mockResolvedValue(summary());
  session.api.liveSnapshot.mockResolvedValue(snapshot());
});

afterEach(() => {
  cleanup();
  expect(vi.getTimerCount()).toBe(0);
  for (const socket of LiveSocket.instances) {
    expect(socket.send).not.toHaveBeenCalled();
  }
  expect(session.api.updateClassroomLive).not.toHaveBeenCalled();
  expect(session.api.startDebate).not.toHaveBeenCalled();
  expect(session.api.nextDebate).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("ClassroomLive read-only recovery", () => {
  it("discovers a classroom that starts after the offline page is opened", async () => {
    session.api.classroomLive.mockResolvedValueOnce(null);
    render(livePage());
    await settle();
    expect(screen.getByText("Live offline")).toBeTruthy();
    expect(LiveSocket.instances).toHaveLength(0);

    await poll();
    expect(screen.getByText("Published classroom speech")).toBeTruthy();
    expect(screen.queryByText("Live offline")).toBeNull();
    expect(LiveSocket.instances).toHaveLength(1);
    expect(LiveSocket.instances[0].url).toMatch(
      /^ws:\/\/[^/]+\/api\/v1\/live\/debate-a\/events$/,
    );
  });

  it("explains unavailable interaction and follows only the server-issued link as it opens and closes", async () => {
    session.api.liveSnapshot.mockResolvedValueOnce(
      snapshot("debate-a", 1, "Published classroom speech", true, null),
    );
    render(livePage());
    await settle();

    const unavailable = screen.getByRole("button", { name: "Interact" });
    expect(unavailable).toHaveProperty("disabled", true);
    expect(unavailable.getAttribute("aria-describedby")).toBe(
      "live-interaction-unavailable",
    );
    expect(screen.getByRole("status").textContent).toBe(
      "Interaction is available only while the teacher has opened it and responses are being collected.",
    );

    act(() =>
      LiveSocket.instances[0].receive(
        snapshot(
          "debate-a",
          2,
          "Published classroom speech",
          true,
          "/classroom/shared-qr-token",
        ),
      ),
    );
    const interact = screen.getByRole("link", { name: "Interact" });
    expect(interact.getAttribute("href")).toBe("/classroom/shared-qr-token");
    const click = vi.fn((event: MouseEvent) => event.preventDefault());
    interact.addEventListener("click", click, { once: true });
    fireEvent.click(interact);
    expect(click).toHaveBeenCalledOnce();
    expect(interact.getAttribute("href")).toBe("/classroom/shared-qr-token");
    expect(screen.queryByRole("status")).toBeNull();

    act(() =>
      LiveSocket.instances[0].receive(
        snapshot("debate-a", 3, "Published classroom speech", true, null),
      ),
    );
    expect(screen.queryByRole("link", { name: "Interact" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Interact" }).getAttribute("disabled"),
    ).not.toBeNull();
    expect(screen.getByRole("status").textContent).toBe(
      "Interaction is available only while the teacher has opened it and responses are being collected.",
    );
  });

  it("shows the unavailable interaction guidance in Chinese", async () => {
    render(livePage("zh"));
    await settle();
    expect(screen.getByRole("status").textContent).toBe(
      "仅当老师已开启互动且课堂仍在收集回应时可参与。",
    );
  });

  it("keeps one socket while polling and does not overlap pending reads", async () => {
    const waiting = deferred<LiveSummary | null>();
    session.api.classroomLive.mockReturnValueOnce(waiting.promise);
    render(livePage());
    await poll();
    await act(async () => {
      window.dispatchEvent(new Event("online"));
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(session.api.classroomLive).toHaveBeenCalledTimes(1);
    waiting.resolve(summary());
    await settle();
    await poll();
    await poll();
    expect(session.api.classroomLive).toHaveBeenCalledTimes(3);
    expect(session.api.liveSnapshot).toHaveBeenCalledTimes(1);
    expect(LiveSocket.instances).toHaveLength(1);
  });

  it("recovers a failed load and clears the old error", async () => {
    session.api.classroomLive.mockRejectedValueOnce(
      new Error("Failed to fetch"),
    );
    render(livePage());
    await settle();
    expect(screen.getByRole("alert")).toBeTruthy();
    await poll();
    expect(screen.getByText("Published classroom speech")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([
    ["classroomLive", 401],
    ["classroomLive", 403],
    ["liveSnapshot", 401],
    ["liveSnapshot", 403],
  ] as const)(
    "stops after initial %s denies access with HTTP %s",
    async (method, status) => {
      session.api[method].mockRejectedValueOnce(
        new PlatformApiError(status, "Access denied"),
      );
      render(livePage());
      await settle();
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(
        screen.getByText(
          status === 401
            ? "Please sign in before continuing."
            : "This account is not allowed to perform that action.",
        ),
      ).toBeTruthy();
      expect(screen.getByText("Live offline")).toBeTruthy();
      expect(screen.queryByText("Published classroom speech")).toBeNull();
      expect(LiveSocket.instances).toHaveLength(0);
      expect(document.querySelector("audio")?.getAttribute("src")).toBeNull();
      await poll();
      await act(async () => {
        window.dispatchEvent(new Event("online"));
        window.dispatchEvent(new Event("focus"));
        document.dispatchEvent(new Event("visibilitychange"));
      });
      expect(session.api.classroomLive).toHaveBeenCalledTimes(1);
      expect(session.api[method]).toHaveBeenCalledTimes(1);
      expect(LiveSocket.instances).toHaveLength(0);
    },
  );

  it.each([401, 403])(
    "clears content and audio when an online classroom poll returns %s",
    async (status) => {
      session.api.liveSnapshot.mockResolvedValue(playingSnapshot());
      vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValue(
        new Error("Playback blocked"),
      );
      render(livePage());
      await settle();
      expect(screen.getByText("Published classroom speech")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Play audio" })).toBeTruthy();
      expect(document.querySelector("audio")?.getAttribute("src")).toBeTruthy();
      const socket = LiveSocket.instances[0];
      session.api.classroomLive.mockRejectedValueOnce(
        new PlatformApiError(status, "Access denied"),
      );
      await poll();
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(screen.getByText("Live offline")).toBeTruthy();
      expect(screen.queryByText("Published classroom speech")).toBeNull();
      expect(screen.queryByRole("button", { name: "Play audio" })).toBeNull();
      expect(document.querySelector("audio")?.getAttribute("src")).toBeNull();
      expect(socket.close).toHaveBeenCalledTimes(1);
      await poll();
      await act(async () => window.dispatchEvent(new Event("focus")));
      expect(session.api.classroomLive).toHaveBeenCalledTimes(2);
      expect(LiveSocket.instances).toHaveLength(1);
    },
  );

  it.each([4401, 4403])(
    "clears a denied WebSocket %s even with stale session state and a pending poll",
    async (code) => {
      session.api.liveSnapshot.mockResolvedValue(playingSnapshot());
      vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValue(
        new Error("Playback blocked"),
      );
      const user = session.user;
      render(livePage());
      await settle();
      expect(screen.getByRole("button", { name: "Play audio" })).toBeTruthy();
      const socket = LiveSocket.instances[0];
      const lateMessage = socket.onmessage;
      const waiting = deferred<LiveSummary | null>();
      session.api.classroomLive.mockReturnValueOnce(waiting.promise);
      await poll();
      act(() => socket.disconnect(code));
      expect(session.user).toBe(user);
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(
        screen.getByText(
          code === 4401
            ? "Please sign in before continuing."
            : "This account is not allowed to perform that action.",
        ),
      ).toBeTruthy();
      expect(screen.getByText("Live offline")).toBeTruthy();
      expect(screen.queryByText("Published classroom speech")).toBeNull();
      expect(screen.queryByRole("button", { name: "Play audio" })).toBeNull();
      expect(document.querySelector("audio")?.getAttribute("src")).toBeNull();
      expect(socket.close).toHaveBeenCalledTimes(1);
      waiting.resolve(summary());
      await settle();
      act(() =>
        lateMessage?.(
          new MessageEvent("message", {
            data: JSON.stringify(snapshot("debate-a", 10, "Denied content")),
          }),
        ),
      );
      await poll();
      await act(async () => window.dispatchEvent(new Event("online")));
      expect(screen.queryByText("Denied content")).toBeNull();
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(session.api.classroomLive).toHaveBeenCalledTimes(2);
      expect(session.api.liveSnapshot).toHaveBeenCalledTimes(1);
      expect(LiveSocket.instances).toHaveLength(1);
    },
  );

  it("reconnects a closed socket without sending controller commands", async () => {
    render(livePage());
    await settle();
    const first = LiveSocket.instances[0];
    act(() => first.disconnect());
    expect(screen.getByRole("alert")).toBeTruthy();
    session.api.liveSnapshot.mockResolvedValue(
      snapshot("debate-a", 2, "Recovered text"),
    );
    await poll();
    expect(first.close).toHaveBeenCalledTimes(1);
    expect(LiveSocket.instances).toHaveLength(2);
    expect(screen.getByText("Recovered text")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("becomes offline when the lease ends and discovers the next broadcast", async () => {
    render(livePage());
    await settle();
    const first = LiveSocket.instances[0];
    act(() => first.receive(snapshot("debate-a", 2, "", false)));
    expect(screen.getByText("Live offline")).toBeTruthy();
    expect(first.close).toHaveBeenCalledTimes(1);
    session.api.classroomLive
      .mockResolvedValueOnce(null)
      .mockResolvedValue(summary("debate-b"));
    await poll();
    expect(LiveSocket.instances).toHaveLength(1);
    session.api.liveSnapshot.mockResolvedValue(
      snapshot("debate-b", 1, "New broadcast"),
    );
    await poll();
    expect(screen.getByText("New broadcast")).toBeTruthy();
    expect(LiveSocket.instances).toHaveLength(2);
  });

  it("clears the stage if the course lookup becomes offline before a socket event", async () => {
    render(livePage());
    await settle();
    session.api.classroomLive.mockResolvedValue(null);
    await poll();
    expect(screen.getByText("Live offline")).toBeTruthy();
    expect(screen.queryByText("Published classroom speech")).toBeNull();
    expect(LiveSocket.instances[0].close).toHaveBeenCalledTimes(1);
  });

  it("resets sequence for a new Debate and ignores the old socket", async () => {
    session.api.liveSnapshot.mockResolvedValueOnce(
      snapshot("debate-a", 99, "Old broadcast"),
    );
    render(livePage());
    await settle();
    const first = LiveSocket.instances[0];
    const staleMessage = first.onmessage;
    session.api.classroomLive.mockResolvedValue(summary("debate-b"));
    session.api.liveSnapshot.mockResolvedValue(
      snapshot("debate-b", 1, "New broadcast"),
    );
    await poll();
    expect(screen.getByText("New broadcast")).toBeTruthy();
    act(() => {
      staleMessage?.(
        new MessageEvent("message", {
          data: JSON.stringify(snapshot("debate-a", 100, "Late old text")),
        }),
      );
      LiveSocket.instances[1].receive(
        snapshot("debate-b", 0, "Stale new text"),
      );
    });
    expect(screen.getByText("New broadcast")).toBeTruthy();
    expect(screen.queryByText("Late old text")).toBeNull();
    expect(screen.queryByText("Stale new text")).toBeNull();
    expect(first.close).toHaveBeenCalledTimes(1);
  });

  it("ignores an old course snapshot that resolves after the course changes", async () => {
    const waiting = deferred<LiveSnapshot>();
    session.api.liveSnapshot.mockReturnValueOnce(waiting.promise);
    const view = render(livePage());
    await settle();
    session.user.courses = [{ course_id: "course-b" }];
    session.api.classroomLive.mockResolvedValue(
      summary("debate-b", "course-b"),
    );
    session.api.liveSnapshot.mockResolvedValue(
      snapshot("debate-b", 1, "New course"),
    );
    view.rerender(livePage());
    await settle();
    waiting.resolve(snapshot("debate-a", 99, "Previous course"));
    await settle();
    expect(screen.getByText("New course")).toBeTruthy();
    expect(screen.queryByText("Previous course")).toBeNull();
    expect(LiveSocket.instances).toHaveLength(1);
    expect(LiveSocket.instances[0].url).toContain("/debate-b/");
  });

  it("ignores a delayed lookup error from the previous course", async () => {
    const waiting = deferred<LiveSummary | null>();
    session.api.classroomLive.mockReturnValueOnce(waiting.promise);
    const view = render(livePage());
    session.user.courses = [{ course_id: "course-b" }];
    session.api.classroomLive.mockResolvedValue(
      summary("debate-b", "course-b"),
    );
    session.api.liveSnapshot.mockResolvedValue(
      snapshot("debate-b", 1, "New course"),
    );
    view.rerender(livePage());
    await settle();
    waiting.reject(new Error("Previous course unavailable"));
    await settle();
    expect(screen.getByText("New course")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("cleans up timers and listeners and discards a snapshot after unmount", async () => {
    const removeWindowListener = vi.spyOn(window, "removeEventListener");
    const removeDocumentListener = vi.spyOn(document, "removeEventListener");
    const waiting = deferred<LiveSnapshot>();
    session.api.liveSnapshot.mockReturnValueOnce(waiting.promise);
    const view = render(livePage());
    await settle();
    view.unmount();
    waiting.resolve(snapshot());
    await settle();
    await act(async () => {
      window.dispatchEvent(new Event("online"));
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(session.api.classroomLive).toHaveBeenCalledTimes(1);
    expect(LiveSocket.instances).toHaveLength(0);
    expect(removeWindowListener).toHaveBeenCalledWith(
      "online",
      expect.any(Function),
    );
    expect(removeWindowListener).toHaveBeenCalledWith(
      "focus",
      expect.any(Function),
    );
    expect(removeDocumentListener).toHaveBeenCalledWith(
      "visibilitychange",
      expect.any(Function),
    );
  });

  it("closes the previous course immediately when membership is removed", async () => {
    const view = render(livePage());
    await settle();
    session.user.courses = [];
    view.rerender(livePage());
    expect(screen.getByText("Live offline")).toBeTruthy();
    expect(screen.queryByText("Published classroom speech")).toBeNull();
    expect(LiveSocket.instances[0].close).toHaveBeenCalledTimes(1);
    await poll();
    expect(session.api.classroomLive).toHaveBeenCalledTimes(1);
  });

  it("ignores old audio failures after switching to another Debate", async () => {
    const playing = playingSnapshot();
    const waiting = deferred<void>();
    vi.mocked(HTMLMediaElement.prototype.play).mockReturnValueOnce(
      waiting.promise,
    );
    session.api.liveSnapshot.mockResolvedValueOnce(playing);
    render(livePage());
    await settle();
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1);
    session.api.classroomLive.mockResolvedValue(summary("debate-b"));
    session.api.liveSnapshot.mockResolvedValue(
      snapshot("debate-b", 1, "New broadcast"),
    );
    await poll();
    waiting.reject(new Error("Previous media failed"));
    await settle();
    expect(screen.getByText("New broadcast")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Play audio" })).toBeNull();
  });

  it.each(["autoplay", "media_error"])(
    "removes the audio action after %s failure when the same Debate advances to text",
    async (failure) => {
      session.api.liveSnapshot.mockResolvedValueOnce(playingSnapshot());
      if (failure === "autoplay") {
        vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValueOnce(
          new Error("Playback blocked"),
        );
      }
      render(livePage());
      await settle();
      const audio = document.querySelector("audio")!;
      if (failure === "media_error") fireEvent.error(audio);
      expect(screen.getByRole("button", { name: "Play audio" })).toBeTruthy();

      const textOnly = playingSnapshot();
      textOnly.sequence = 2;
      textOnly.turns.push({
        ...textOnly.turns[0],
        id: "turn-b",
        turn_index: 1,
        speech: "Text continues without speech audio",
        audio_url: null,
      });
      textOnly.playback = {
        ...textOnly.playback!,
        status: "waiting_next",
        current_turn_id: "turn-b",
        control_version: 2,
      };
      act(() => LiveSocket.instances[0].receive(textOnly));
      expect(
        screen.getByText("Text continues without speech audio"),
      ).toBeTruthy();
      expect(audio.getAttribute("src")).toBeNull();
      expect(screen.queryByRole("button", { name: "Play audio" })).toBeNull();
      fireEvent.error(audio);
      expect(screen.queryByRole("button", { name: "Play audio" })).toBeNull();
      expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1);
      expect(LiveSocket.instances).toHaveLength(1);
    },
  );

  it("rechecks immediately when the browser comes back online", async () => {
    session.api.classroomLive.mockResolvedValueOnce(null);
    render(livePage());
    await settle();
    await act(async () => window.dispatchEvent(new Event("online")));
    expect(screen.getByText("Published classroom speech")).toBeTruthy();
    expect(session.api.classroomLive).toHaveBeenCalledTimes(2);
  });

  it("drops invalid socket snapshots and recovers through an authenticated read", async () => {
    render(livePage());
    await settle();
    act(() =>
      LiveSocket.instances[0].receive(
        snapshot("other-debate", 2, "Wrong course"),
      ),
    );
    expect(screen.queryByText("Wrong course")).toBeNull();
    expect(screen.getByRole("alert")).toBeTruthy();
    await poll();
    expect(LiveSocket.instances).toHaveLength(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
