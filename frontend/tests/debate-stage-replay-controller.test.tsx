import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BetaDebateStage } from "../components/debate-beta/stage";
import {
  type DebatePlaybackApi,
  type PlaybackSocket,
} from "../components/debate/stage";
import type { DebateDetail, DebatePlaybackState } from "../lib/api";

vi.mock("../components/avatar/avatar-preview", () => ({
  AvatarPreview: ({ fallbackLabel }: { fallbackLabel?: string }) => (
    <div>{fallbackLabel ?? "avatar"}</div>
  ),
}));

vi.mock("../components/stage3d/scholar-scene", () => ({
  ScholarScene: ({
    bubbleText,
    visuals,
    overlay,
  }: {
    overlay?: import("react").ReactNode;
    bubbleText?: string;
    visuals: Record<string, string>;
  }) => (
    <aside data-motion={Object.values(visuals)[0]} data-testid="speech-bubble">
      {bubbleText}
      {overlay}
    </aside>
  ),
}));

afterEach(() => cleanup());

const debateId = "20000000-0000-4000-8000-000000000001";
const participantId = "30000000-0000-4000-8000-000000000001";
const turnId = "40000000-0000-4000-8000-000000000001";
const epoch = "50000000-0000-4000-8000-000000000001";

type Listener = (event: Event) => void;

class ReplaySocket implements PlaybackSocket {
  readyState = 0;
  readonly sent: string[] = [];
  private readonly listeners = new Map<string, Set<Listener>>();

  send(data: string): void {
    if (this.readyState !== 1) {
      throw new Error("socket is not open");
    }
    this.sent.push(data);
  }

  close(): void {
    this.readyState = 3;
  }

  addEventListener(type: string, listener: Listener): void {
    const listeners = this.listeners.get(type) ?? new Set<Listener>();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.get(type)?.delete(listener);
  }

  hasListeners(type: string): boolean {
    return (this.listeners.get(type)?.size ?? 0) > 0;
  }

  emitOpen(): void {
    this.readyState = 1;
    this.listeners
      .get("open")
      ?.forEach((listener) => listener(new Event("open")));
  }

  emitClose(code = 1006): void {
    this.readyState = 3;
    this.listeners
      .get("close")
      ?.forEach((listener) =>
        listener({ type: "close", code } as unknown as Event),
      );
  }

  emitMessage(value: Record<string, unknown>): void {
    this.listeners
      .get("message")
      ?.forEach((listener) =>
        listener(new MessageEvent("message", { data: JSON.stringify(value) })),
      );
  }

  commands(): Record<string, unknown>[] {
    return this.sent.map((item) => JSON.parse(item) as Record<string, unknown>);
  }
}

function detail(): DebateDetail {
  return {
    id: debateId,
    course_id: "10000000-0000-4000-8000-000000000002",
    topic: "How should a classroom balance memory and change?",
    background: "",
    status: "completed",
    created_at: "2026-09-07T00:00:00Z",
    audio_restore_needed: false,
    prepared_turns: 2,
    expected_turns: 2,
    preview: null,
    output_language: "en",
    turn_protocol: "segments_v2",
    preview_turns: [],
    final_input_frozen: true,
    stall: null,
    revision: 1,
    last_sequence: 4,
    rule_set_id: "ordered_multi_expert_mutual_learning_v1",
    round_count: 2,
    participants: [
      {
        id: participantId,
        slot: "A",
        order_index: 0,
        agent_id: "60000000-0000-4000-8000-000000000001",
        agent_name: "River Steward",
        agent_version_id: "70000000-0000-4000-8000-000000000001",
        version_label: "V2.0",
        knowledge_snapshot_id: "80000000-0000-4000-8000-000000000001",
        avatar_config: {
          template_id: "wave1-default-head",
          material_theme: "demo",
          eye_color: null,
          default_expression: "neutral",
          expression_strength: "medium",
          motion_style: "calm",
        },
        effective_voice_profile_id: null,
        voice_fallback_active: true,
        stance_mode: "assigned",
        initial_stance: "support",
        current_stance: "support",
      },
    ],
    public_turns: [
      {
        id: turnId,
        participant_id: participantId,
        round_no: 1,
        turn_index: 0,
        speech: "A retained paragraph is ready for replay.",
        retrieval_status: "matched",
        grounding_mode: "rag_grounded",
        sources: [],
        audio_ready: true,
        segment_turn: {
          schema_version: "segment_turn_v2",
          segments: [
            {
              text: "A retained paragraph is ready for replay.",
              source_ids: [],
              reply_to: null,
            },
          ],
        },
        source_details: [],
      },
    ],
    playback: {
      status: "completed",
      mode: "live",
      current_turn_id: null,
      cursor_ms: 0,
      control_version: 7,
      next_turn_ready: false,
    },
    interaction_status: "closed",
    insight_status: "not_started",
    report_status: "not_started",
  };
}

function apiFor(initial: DebateDetail): DebatePlaybackApi {
  const replayState: DebatePlaybackState = {
    ...initial.playback,
    status: "ready",
    mode: "replay",
    current_turn_id: turnId,
    control_version: initial.playback.control_version + 1,
  };
  return {
    startDebate: vi.fn(),
    advanceDebatePlayback: vi.fn(),
    replayDebate: vi.fn().mockResolvedValue(replayState),
    pauseDebate: vi.fn(),
    resumeDebate: vi.fn(),
    freezeFinalInput: vi.fn(),
    retryDebatePreparation: vi.fn(),
  };
}

function acquired(): Record<string, unknown> {
  return {
    message_id: "91000000-0000-4000-8000-000000000001",
    message_type: "controller.acquired",
    result_version: 1,
    debate_id: debateId,
    occurred_at: "2026-09-07T00:00:00Z",
    command_id: "92000000-0000-4000-8000-000000000001",
    controller_epoch: epoch,
    control_version: 7,
  };
}

function renderStage(
  kind: "beta",
  initial: DebateDetail,
  api: DebatePlaybackApi,
  socket: ReplaySocket,
) {
  const props = {
    api,
    debateId,
    detail: initial,
    socketFactory: () => socket,
  };
  return <BetaDebateStage {...props} />;
}

describe("terminal segments replay controller", () => {
  it("keeps messages flowing without manual Pause or Collect controls", () => {
    const initial = detail();
    render(
      <BetaDebateStage
        api={apiFor(initial)}
        debateId={debateId}
        detail={initial}
        socketFactory={() => new ReplaySocket()}
        joinUrl="https://example.test/classroom/test"
        joinCodeVisible={false}
        headerActions={(replayButton) => (
          <>
            <button>Interact</button>
            {replayButton}
          </>
        )}
      />,
    );
    expect(
      screen.getByLabelText("Classroom messages").getAttribute("data-paused"),
    ).toBe("false");
    expect(
      screen.queryByRole("button", { name: /Pause|Collect|Resume messages/i }),
    ).toBeNull();
  });

  it("places terminal Replay between Back and Conclude while Next is disabled", () => {
    const initial = detail();
    render(
      <BetaDebateStage
        api={apiFor(initial)}
        debateId={debateId}
        detail={initial}
        socketFactory={() => new ReplaySocket()}
        headerActions={(replayButton) => (
          <>
            <a href="/teacher/debates">Back</a>
            {replayButton}
            <button>Conclude</button>
          </>
        )}
      />,
    );
    const next = screen.getByRole("button", { name: "Next" });
    expect(next).toHaveProperty("disabled", true);
    const panel = next.closest('[role="group"]')!;
    expect(
      Array.from(panel.querySelectorAll("button,a")).map(
        (node) => node.textContent || node.getAttribute("aria-label"),
      ),
      // The stage's music key (2026-11-03) ends the dock; it has no text.
    ).toEqual([
      "Next",
      "Back",
      "Review",
      "Conclude",
      "Transcript",
      "No music yet",
    ]);
    expect(
      screen.queryByRole("button", { name: "Replay whole debate" }),
    ).toBeNull();
    expect(panel.querySelector('[class*="turnProgress"]')).toBeNull();
  });

  it("beta recovers a stale entry acquire and keeps newer public state when its grant arrives", async () => {
    const initial = detail();
    initial.status = "running";
    initial.playback = {
      ...initial.playback,
      status: "waiting_next",
      current_turn_id: turnId,
      next_turn_ready: true,
    };
    const socket = new ReplaySocket();
    const api = apiFor(initial);
    const authority = vi.fn();
    render(
      <BetaDebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
        onAuthorityChange={authority}
      />,
    );
    expect(screen.queryByRole("button", { name: /^Replay/ })).toBeNull();
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    act(() => socket.emitOpen());
    expect(socket.commands()).toHaveLength(1);
    act(() =>
      socket.emitMessage({
        ...acquired(),
        message_type: "command.rejected",
        code: "stale_control_version",
        current_control_version: 9,
      }),
    );
    await waitFor(() => expect(socket.commands()).toHaveLength(2));
    expect(socket.commands()[1]?.expected_control_version).toBe(9);
    // A public event may already have advanced the locally known version.
    act(() => socket.emitMessage({ ...acquired(), control_version: 8 }));
    await waitFor(() =>
      expect(authority).toHaveBeenLastCalledWith(
        expect.objectContaining({ controllerReady: true }),
      ),
    );
    expect(screen.getByRole("button", { name: "Next" })).toHaveProperty(
      "disabled",
      false,
    );
    expect(screen.getByRole("heading", { name: initial.topic })).toBeTruthy();
  });

  it("beta restores the current speech bubble when opened while waiting for Next", async () => {
    const initial = detail();
    initial.status = "running";
    initial.playback = {
      ...initial.playback,
      status: "waiting_next",
      current_turn_id: turnId,
    };
    const socket = new ReplaySocket();
    render(renderStage("beta", initial, apiFor(initial), socket));
    await waitFor(() =>
      expect(screen.getByTestId("speech-bubble").textContent).toContain(
        "A retained paragraph",
      ),
    );
  });

  it("beta reveals saved speech with audio time and stops mouth movement on pause", async () => {
    const initial = detail();
    initial.status = "running";
    initial.playback = {
      ...initial.playback,
      status: "ready",
      current_turn_id: turnId,
    };
    const socket = new ReplaySocket();
    const play = vi
      .spyOn(HTMLMediaElement.prototype, "play")
      .mockResolvedValue(undefined);
    try {
      render(renderStage("beta", initial, apiFor(initial), socket));
      const bubble = screen.getByTestId("speech-bubble");
      const audio = screen.getByLabelText(
        "Classroom audio",
      ) as HTMLAudioElement;
      Object.defineProperty(audio, "duration", {
        configurable: true,
        value: 10,
      });
      Object.defineProperty(audio, "currentTime", {
        configurable: true,
        writable: true,
        value: 0,
      });
      expect(bubble.textContent).toBe("");

      await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
      act(() => socket.emitOpen());
      act(() => socket.emitMessage(acquired()));
      await waitFor(() =>
        expect(
          socket
            .commands()
            .some(
              (command) => command.command_type === "playback.media.prepare",
            ),
        ).toBe(true),
      );
      act(() =>
        socket.emitMessage({
          ...acquired(),
          message_type: "media.prepared",
          turn_id: turnId,
          media_url: `/api/v1/debates/${debateId}/audio/${turnId}?media_ticket=${"a".repeat(43)}`,
        }),
      );
      await waitFor(() =>
        expect(
          socket
            .commands()
            .some((command) => command.command_type === "playback.started_ack"),
        ).toBe(true),
      );
      fireEvent.loadedMetadata(audio);
      audio.currentTime = 5;
      fireEvent.timeUpdate(audio);
      // Local playback reveals the saved speech without waiting for WebSocket echo.
      expect(bubble.textContent).toBe(
        initial.public_turns[0].speech.slice(
          0,
          Math.round(initial.public_turns[0].speech.length / 2),
        ),
      );

      act(() =>
        socket.emitMessage({
          event_id: "90000000-0000-4000-8000-000000000005",
          event_type: "playback.started",
          event_version: 1,
          debate_id: debateId,
          sequence: 5,
          occurred_at: "2026-09-08T00:00:00Z",
          payload: {
            turn_id: turnId,
            slot: "A",
            round_no: 1,
            speech: initial.public_turns[0].speech,
            sources: [],
            playback_url: `/api/v1/debates/${debateId}/audio/${turnId}`,
            avatar_states: [
              {
                participant_id: participantId,
                slot: "A",
                motion_state: "speaking",
                expression: "neutral",
              },
            ],
            cursor_ms: 0,
          },
        }),
      );
      expect(bubble.textContent).toBe(
        initial.public_turns[0].speech.slice(
          0,
          Math.round(initial.public_turns[0].speech.length / 2),
        ),
      );
      fireEvent.playing(audio);
      expect(bubble.getAttribute("data-motion")).toBe("speaking");
      fireEvent.pause(audio);
      expect(bubble.getAttribute("data-motion")).toBe("idle");
      expect(bubble.textContent).toBeTruthy();
      Object.defineProperty(audio, "error", {
        configurable: true,
        value: { code: 3 },
      });
      fireEvent.error(audio);
      expect(bubble.textContent).toBe(initial.public_turns[0].speech);
      expect(bubble.getAttribute("data-motion")).toBe("idle");
    } finally {
      play.mockRestore();
    }
  });

  it("beta keeps the bubble after audio ends and releases authority until an explicit Replay", async () => {
    const initial = detail();
    initial.status = "running";
    initial.playback = {
      ...initial.playback,
      status: "playing",
      current_turn_id: turnId,
    };
    const socket = new ReplaySocket();
    const api = apiFor(initial);
    render(renderStage("beta", initial, api, socket));
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    act(() => socket.emitOpen());
    act(() => socket.emitMessage(acquired()));
    const emit = (
      type: string,
      sequence: number,
      payload: Record<string, unknown>,
    ) =>
      socket.emitMessage({
        event_id: `90000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
        event_type: type,
        event_version: 1,
        debate_id: debateId,
        sequence,
        occurred_at: "2026-09-08T00:00:00Z",
        payload,
      });
    act(() =>
      emit("playback.completed", 5, { turn_id: turnId, control_version: 8 }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("speech-bubble").textContent).toContain(
        "A retained paragraph",
      ),
    );
    act(() => emit("debate.completed", 6, {}));
    act(() =>
      socket.emitMessage({
        ...acquired(),
        message_type: "controller.revoked",
        reason: "debate_terminal",
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: /^(?:Review|Replay whole debate)$/,
        }),
      ).toHaveProperty("disabled", false),
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(
      socket
        .commands()
        .filter((item) => item.command_type === "playback.controller.acquire"),
    ).toHaveLength(1);
    expect(screen.getByTestId("speech-bubble").textContent).toContain(
      "A retained paragraph",
    );
    fireEvent.click(
      screen.getByRole("button", { name: /^(?:Review|Replay whole debate)$/ }),
    );
    expect(
      socket
        .commands()
        .filter((item) => item.command_type === "playback.controller.acquire"),
    ).toHaveLength(2);
    act(() => socket.emitMessage({ ...acquired(), control_version: 9 }));
    await waitFor(() => expect(api.replayDebate).toHaveBeenCalledTimes(1));
  });

  it.each(["beta"] as const)(
    "%s waits for an opening socket before acquiring replay control",
    async (kind) => {
      const initial = detail();
      const api = apiFor(initial);
      const socket = new ReplaySocket();
      render(renderStage(kind, initial, api, socket));

      const replay = await screen.findByRole("button", {
        name: /^(?:Review|Replay whole debate)$/,
      });
      await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
      fireEvent.click(replay);

      expect(socket.commands()).toHaveLength(0);
      expect(api.replayDebate).not.toHaveBeenCalled();

      socket.emitOpen();
      await waitFor(() =>
        expect(
          socket
            .commands()
            .filter(
              (command) =>
                command.command_type === "playback.controller.acquire",
            ),
        ).toHaveLength(1),
      );
      socket.emitMessage(acquired());

      await waitFor(() =>
        expect(api.replayDebate).toHaveBeenCalledWith(debateId, 7),
      );
      if (kind === "beta") {
        expect(screen.queryByRole("button", { name: "Review" })).toBeNull();
      } else {
        expect(
          screen.getByRole("button", { name: "Replay whole debate" }),
        ).toBeTruthy();
      }
    },
  );

  it.each(["beta"] as const)(
    "%s disables replay after its terminal socket is gone",
    async (kind) => {
      const initial = detail();
      const socket = new ReplaySocket();
      render(renderStage(kind, initial, apiFor(initial), socket));
      const replay = await screen.findByRole("button", {
        name: /^(?:Review|Replay whole debate)$/,
      });
      socket.emitOpen();
      socket.emitClose();

      await waitFor(() => expect(replay).toHaveProperty("disabled", true));
    },
  );

  it.each(["beta"] as const)(
    "%s offers reconnect when the network drops during retained replay",
    async (kind) => {
      const initial = detail();
      const api = apiFor(initial);
      const socket = new ReplaySocket();
      render(renderStage(kind, initial, api, socket));
      const replay = await screen.findByRole("button", {
        name: /^(?:Review|Replay whole debate)$/,
      });
      await waitFor(() => expect(socket.hasListeners("open")).toBe(true));

      act(() => socket.emitOpen());
      fireEvent.click(replay);
      await waitFor(() =>
        expect(
          socket
            .commands()
            .filter(
              (command) =>
                command.command_type === "playback.controller.acquire",
            ),
        ).toHaveLength(1),
      );
      act(() => socket.emitMessage(acquired()));
      await waitFor(() => expect(api.replayDebate).toHaveBeenCalledTimes(1));

      act(() => socket.emitClose(1006));

      if (kind === "beta") {
        expect(screen.queryByRole("button", { name: "Reconnect" })).toBeNull();
      } else {
        await waitFor(() =>
          expect(
            screen.getByRole("button", { name: "Reconnect" }),
          ).toBeTruthy(),
        );
      }
      expect(api.replayDebate).toHaveBeenCalledTimes(1);
    },
  );
});

describe("saved media failure recovery", () => {
  it.each(["beta"] as const)(
    "%s recovers a refused Next in place without regeneration",
    async (kind) => {
      const initial = detail();
      initial.status = "running";
      initial.playback = {
        ...initial.playback,
        status: "waiting_next",
        current_turn_id: turnId,
        next_turn_ready: true,
      };
      const refreshed = {
        ...initial,
        playback: { ...initial.playback, control_version: 8 },
      };
      const refreshSnapshot = vi.fn().mockResolvedValue(refreshed);
      const socket = new ReplaySocket();
      const api = apiFor(initial);
      vi.mocked(api.advanceDebatePlayback).mockRejectedValueOnce(
        new Error("The platform request could not be completed."),
      );
      const props = {
        api,
        debateId,
        detail: initial,
        socketFactory: () => socket,
        refreshSnapshot,
      };
      render(<BetaDebateStage {...props} />);
      await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
      act(() => socket.emitOpen());
      act(() => socket.emitMessage(acquired()));
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
      await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1));
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Next" })).toHaveProperty(
          "disabled",
          false,
        ),
      );
      expect(api.retryDebatePreparation).not.toHaveBeenCalled();
      // #100: a failed Next stays visible instead of being silently cleared,
      // while Next remains enabled so the teacher can retry in place.
      expect(
        screen.getByText("The platform request could not be completed."),
      ).toBeTruthy();
      expect(screen.queryByRole("button", { name: "Regenerate" })).toBeNull();
      expect(
        screen.queryByText("Playback did not start. You can retry this turn."),
      ).toBeNull();
    },
  );

  it.each(["beta"] as const)(
    "%s ignores duplicated prepared media and retries a failed media ticket once",
    async (kind) => {
      const initial = detail();
      initial.status = "running";
      // Saved media can only play alongside its published speech.
      initial.playback = {
        ...initial.playback,
        status: "ready",
        current_turn_id: turnId,
      };
      const refreshed = { ...initial, last_sequence: 5 };
      const refreshSnapshot = vi.fn().mockResolvedValue(refreshed);
      const socket = new ReplaySocket();
      const api = apiFor(initial);
      let rejectPlay: (reason: unknown) => void = () => {};
      const play = vi
        .spyOn(HTMLMediaElement.prototype, "play")
        .mockImplementationOnce(
          () =>
            new Promise<void>((_resolve, reject) => {
              rejectPlay = reject;
            }),
        )
        .mockResolvedValue(undefined);
      const props = {
        api,
        debateId,
        detail: initial,
        socketFactory: () => socket,
        refreshSnapshot,
      };
      render(<BetaDebateStage {...props} />);
      await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
      act(() => socket.emitOpen());
      if (kind === "beta") {
        expect(
          screen
            .getByLabelText(/Turn \d+ of \d+, connected/)
            .getAttribute("data-connected"),
        ).toBe("true");
        expect(screen.queryByText("Connected")).toBeNull();
      }
      act(() => socket.emitMessage(acquired()));
      const prepared = {
        ...acquired(),
        message_type: "media.prepared",
        turn_id: turnId,
        media_url: `/api/v1/debates/${debateId}/audio/${turnId}?media_ticket=${"a".repeat(43)}`,
      };
      act(() => {
        socket.emitMessage(prepared);
        socket.emitMessage(prepared);
      });
      await waitFor(() => expect(play).toHaveBeenCalledTimes(1));
      await act(async () =>
        rejectPlay(new DOMException("Interrupted", "AbortError")),
      );
      expect(
        socket
          .commands()
          .filter((x) => x.command_type === "playback.play_failed"),
      ).toHaveLength(1);
      act(() =>
        socket.emitMessage({
          event_id: "90000000-0000-4000-8000-000000000005",
          event_type: "error",
          event_version: 1,
          debate_id: debateId,
          sequence: 5,
          occurred_at: "2026-09-08T00:00:00Z",
          payload: { code: "playback_failed", recoverable: true },
        }),
      );
      await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1));
      await waitFor(() =>
        expect(
          socket
            .commands()
            .filter((x) => x.command_type === "playback.media.prepare").length,
        ).toBeGreaterThanOrEqual(1),
      );
      act(() =>
        socket.emitMessage({
          ...prepared,
          media_url: `/api/v1/debates/${debateId}/audio/${turnId}?media_ticket=${"b".repeat(43)}`,
        }),
      );
      await waitFor(() =>
        expect(
          socket
            .commands()
            .filter((x) => x.command_type === "playback.started_ack"),
        ).toHaveLength(1),
      );
      expect(api.retryDebatePreparation).not.toHaveBeenCalled();
      expect(
        screen.queryByText("Playback did not start. You can retry this turn."),
      ).toBeNull();
      play.mockRestore();
    },
  );
});

describe("ready state media handoff", () => {
  it.each(["beta"] as const)(
    "%s prepares the next saved audio when refreshed detail arrives before the REST callback",
    async (kind) => {
      const initial = detail();
      initial.status = "running";
      initial.playback = {
        ...initial.playback,
        status: "waiting_next",
        current_turn_id: turnId,
        next_turn_ready: true,
      };
      const successor = "40000000-0000-4000-8000-000000000002";
      const next = {
        ...initial,
        playback: {
          ...initial.playback,
          status: "ready" as const,
          current_turn_id: successor,
          control_version: 8,
          next_turn_ready: false,
        },
      };
      const socket = new ReplaySocket();
      const api = apiFor(initial);
      let resolveNext!: (state: DebatePlaybackState) => void;
      vi.mocked(api.advanceDebatePlayback).mockImplementation(
        () =>
          new Promise((resolve) => {
            resolveNext = resolve;
          }),
      );
      const refreshSnapshot = vi.fn().mockResolvedValue(next);
      const factory = () => socket;
      const view = (value: DebateDetail) => {
        const props = {
          api,
          debateId,
          detail: value,
          socketFactory: factory,
          refreshSnapshot,
        };
        return <BetaDebateStage {...props} />;
      };
      const rendered = render(view(initial));
      await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
      act(() => socket.emitOpen());
      act(() => socket.emitMessage(acquired()));
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
      await waitFor(() =>
        expect(api.advanceDebatePlayback).toHaveBeenCalledTimes(1),
      );
      rendered.rerender(view(next));
      await waitFor(() =>
        expect(
          socket
            .commands()
            .filter(
              (command) =>
                command.command_type === "playback.media.prepare" &&
                command.turn_id === successor,
            ),
        ).toHaveLength(1),
      );
      await act(async () => resolveNext(next.playback));
      await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1));
      expect(
        socket
          .commands()
          .filter(
            (command) =>
              command.command_type === "playback.media.prepare" &&
              command.turn_id === successor,
          ),
      ).toHaveLength(1);
      expect(api.advanceDebatePlayback).toHaveBeenCalledTimes(1);
      expect(api.retryDebatePreparation).not.toHaveBeenCalled();
    },
  );
});

describe("waiting generation reconciliation", () => {
  it("enables Next from a committed snapshot when the ready notification was missed", async () => {
    const initial = detail();
    initial.status = "running";
    initial.round_count = 4;
    initial.playback = {
      ...initial.playback,
      status: "waiting_next",
      mode: "live",
      current_turn_id: turnId,
      next_turn_ready: false,
    };
    const ready = {
      ...initial,
      playback: { ...initial.playback, next_turn_ready: true },
    };
    const socket = new ReplaySocket();
    const api = apiFor(initial);
    const successor = "40000000-0000-4000-8000-000000000002";
    const advanced = {
      ...ready,
      playback: {
        ...ready.playback,
        status: "ready" as const,
        current_turn_id: successor,
        control_version: 8,
        next_turn_ready: false,
      },
    };
    vi.mocked(api.advanceDebatePlayback).mockResolvedValue(advanced.playback);
    const refreshSnapshot = vi
      .fn()
      .mockResolvedValueOnce(ready)
      .mockResolvedValue(advanced);
    render(
      <BetaDebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
        refreshSnapshot={refreshSnapshot}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    act(() => socket.emitOpen());
    act(() => socket.emitMessage(acquired()));
    expect(
      (screen.getByRole("button", { name: "Next" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByText("Generating")).toBeTruthy();
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Next" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    );
    expect(screen.getByText("Waiting")).toBeTruthy();
    expect(refreshSnapshot).toHaveBeenCalledTimes(1);
    expect(api.advanceDebatePlayback).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(api.advanceDebatePlayback).toHaveBeenCalledTimes(1),
    );
    await waitFor(() =>
      expect(
        socket
          .commands()
          .some(
            (command) =>
              command.command_type === "playback.media.prepare" &&
              command.turn_id === successor,
          ),
      ).toBe(true),
    );
    expect(screen.getByText("Generating")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Next" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(api.retryDebatePreparation).not.toHaveBeenCalled();
  });
});

it("keeps immediate Next while playing and blocks a duplicate click until the successor is prepared", async () => {
  const initial = detail();
  initial.status = "running";
  initial.round_count = 4;
  initial.playback = {
    ...initial.playback,
    status: "playing",
    mode: "live",
    current_turn_id: turnId,
  };
  const successor = "40000000-0000-4000-8000-000000000002";
  const advanced = {
    ...initial,
    playback: {
      ...initial.playback,
      status: "ready" as const,
      current_turn_id: successor,
      control_version: 8,
    },
  };
  const socket = new ReplaySocket();
  const api = apiFor(initial);
  let resolveNext!: (value: DebatePlaybackState) => void;
  vi.mocked(api.advanceDebatePlayback).mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveNext = resolve;
      }),
  );
  render(
    <BetaDebateStage
      api={api}
      debateId={debateId}
      detail={initial}
      socketFactory={() => socket}
      refreshSnapshot={async () => advanced}
    />,
  );
  await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
  act(() => socket.emitOpen());
  act(() => socket.emitMessage(acquired()));
  expect(screen.getByText("Waiting")).toBeTruthy();
  const next = screen.getByRole("button", {
    name: "Next",
  }) as HTMLButtonElement;
  expect(next.disabled).toBe(false);
  fireEvent.click(next);
  fireEvent.click(next);
  expect(api.advanceDebatePlayback).toHaveBeenCalledTimes(1);
  expect(next.disabled).toBe(true);
  expect(screen.getByText("Generating")).toBeTruthy();
  expect(screen.queryByText("Updating classroom playback…")).toBeNull();
  await act(async () => resolveNext(advanced.playback));
  await waitFor(() =>
    expect(
      socket
        .commands()
        .some(
          (command) =>
            command.command_type === "playback.media.prepare" &&
            command.turn_id === successor,
        ),
    ).toBe(true),
  );
  expect(api.retryDebatePreparation).not.toHaveBeenCalled();
});

it("normal readiness polling does not briefly enable media retry before playback starts", async () => {
  const initial = detail();
  initial.status = "running";
  initial.round_count = 4;
  initial.playback = {
    ...initial.playback,
    status: "preparing",
    mode: "live",
    current_turn_id: turnId,
  };
  const ready = {
    ...initial,
    playback: { ...initial.playback, status: "ready" as const },
  };
  const socket = new ReplaySocket();
  const api = apiFor(initial);
  const refreshSnapshot = vi.fn().mockResolvedValue(ready);
  render(
    <BetaDebateStage
      api={api}
      debateId={debateId}
      detail={initial}
      socketFactory={() => socket}
      refreshSnapshot={refreshSnapshot}
    />,
  );
  await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
  act(() => socket.emitOpen());
  act(() => socket.emitMessage(acquired()));
  await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1), {
    timeout: 3000,
  });
  await waitFor(() =>
    expect(
      document.querySelector('[data-playback-status="ready"]'),
    ).toBeTruthy(),
  );
  expect(screen.getByRole("button", { name: "Next" })).toHaveProperty(
    "disabled",
    true,
  );
  expect(screen.getByText("Generating")).toBeTruthy();
  expect(screen.queryByText("Waiting")).toBeNull();
  expect(api.advanceDebatePlayback).not.toHaveBeenCalled();
  expect(api.retryDebatePreparation).not.toHaveBeenCalled();
});

describe("beta barrage history hydration", () => {
  function hydrateEvent(sequence: number): Record<string, unknown> {
    return {
      event_id: "81000000-0000-4000-8000-000000000003",
      event_type: "interaction.barrage_created",
      event_version: 1,
      debate_id: debateId,
      sequence,
      occurred_at: "2026-09-07T00:00:05Z",
      payload: {
        message_id: "b3000000-0000-4000-8000-000000000003",
        nickname: "Jade",
        raw_text: "live after hydrate",
        sequence: 3,
      },
    };
  }

  it("hydrates the lane from the teacherInteraction snapshot and keeps live events flowing", async () => {
    const initial = detail();
    const socket = new ReplaySocket();
    render(
      <BetaDebateStage
        api={apiFor(initial)}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
        joinUrl="https://example.test/classroom/test"
        joinCodeVisible
        interactionBarrages={[
          {
            id: "b1000000-0000-4000-8000-000000000001",
            nickname: "Ana",
            raw_text: "history one",
          },
          {
            id: "b2000000-0000-4000-8000-000000000002",
            nickname: "Bo",
            raw_text: "history two",
          },
        ]}
      />,
    );

    expect(screen.getByText(/2 messages/)).toBeTruthy();
    expect(screen.getByLabelText("Classroom messages")).toBeTruthy();

    await waitFor(() => expect(socket.hasListeners("message")).toBe(true));
    act(() => socket.emitOpen());
    act(() => socket.emitMessage(acquired()));
    act(() => socket.emitMessage(hydrateEvent(initial.last_sequence + 1)));
    await waitFor(() => expect(screen.getByText(/3 messages/)).toBeTruthy());
  });

  it("does not duplicate shared ids when history arrives after a live event", async () => {
    const initial = detail();
    const socket = new ReplaySocket();
    const shared = {
      id: "b3000000-0000-4000-8000-000000000003",
      nickname: "Jade",
      raw_text: "live after hydrate",
    };
    const view = render(
      <BetaDebateStage
        api={apiFor(initial)}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
        joinUrl="https://example.test/classroom/test"
        joinCodeVisible
      />,
    );

    await waitFor(() => expect(socket.hasListeners("message")).toBe(true));
    act(() => socket.emitOpen());
    act(() => socket.emitMessage(acquired()));
    act(() => socket.emitMessage(hydrateEvent(initial.last_sequence + 1)));
    await waitFor(() => expect(screen.getByText(/1 message/)).toBeTruthy());

    view.rerender(
      <BetaDebateStage
        api={apiFor(initial)}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
        joinUrl="https://example.test/classroom/test"
        joinCodeVisible
        interactionBarrages={[
          shared,
          {
            id: "b4000000-0000-4000-8000-000000000004",
            nickname: "Kai",
            raw_text: "later history",
          },
        ]}
      />,
    );
    await waitFor(() => expect(screen.getByText(/2 messages/)).toBeTruthy());
  });
});
