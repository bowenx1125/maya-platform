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
  DebateStage,
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
  ScholarScene: ({ bubbleText }: { bubbleText?: string }) => (
    <aside data-testid="speech-bubble">{bubbleText}</aside>
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
    rule_set_id: "ordered_multi_agent_rounds_demo_v2",
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
      playback_rate: 1,
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
    listProviderDataCallManifests: vi.fn().mockResolvedValue({
      scope_id: debateId,
      items: [],
    }),
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
  kind: "classic" | "beta",
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
  return kind === "classic" ? (
    <DebateStage {...props} />
  ) : (
    <BetaDebateStage {...props} />
  );
}

describe("terminal segments replay controller", () => {
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
    expect(screen.queryByRole("heading", { name: initial.topic })).toBeNull();
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
        screen.getByRole("button", { name: "Replay whole debate" }),
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
      screen.getByRole("button", { name: "Replay whole debate" }),
    );
    expect(
      socket
        .commands()
        .filter((item) => item.command_type === "playback.controller.acquire"),
    ).toHaveLength(2);
    act(() => socket.emitMessage({ ...acquired(), control_version: 9 }));
    await waitFor(() => expect(api.replayDebate).toHaveBeenCalledTimes(1));
  });

  it.each(["classic", "beta"] as const)(
    "%s waits for an opening socket before acquiring replay control",
    async (kind) => {
      const initial = detail();
      const api = apiFor(initial);
      const socket = new ReplaySocket();
      render(renderStage(kind, initial, api, socket));

      const replay = await screen.findByRole("button", {
        name: "Replay whole debate",
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
      expect(
        screen.getByRole("button", { name: "Replay whole debate" }),
      ).toBeTruthy();
    },
  );

  it.each(["classic", "beta"] as const)(
    "%s disables replay after its terminal socket is gone",
    async (kind) => {
      const initial = detail();
      const socket = new ReplaySocket();
      render(renderStage(kind, initial, apiFor(initial), socket));
      const replay = await screen.findByRole("button", {
        name: "Replay whole debate",
      });
      socket.emitOpen();
      socket.emitClose();

      await waitFor(() => expect(replay).toHaveProperty("disabled", true));
    },
  );

  it.each(["classic", "beta"] as const)(
    "%s offers reconnect when the network drops during retained replay",
    async (kind) => {
      const initial = detail();
      const api = apiFor(initial);
      const socket = new ReplaySocket();
      render(renderStage(kind, initial, api, socket));
      const replay = await screen.findByRole("button", {
        name: "Replay whole debate",
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

      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Reconnect" })).toBeTruthy(),
      );
      expect(api.replayDebate).toHaveBeenCalledTimes(1);
    },
  );
});

describe("saved media failure recovery", () => {
  it.each(["classic", "beta"] as const)(
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
      render(
        kind === "beta" ? (
          <BetaDebateStage {...props} />
        ) : (
          <DebateStage {...props} />
        ),
      );
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
      expect(
        screen.queryByText("The platform request could not be completed."),
      ).toBeNull();
      expect(screen.queryByRole("button", { name: "Regenerate" })).toBeNull();
      expect(
        screen.queryByText("Playback did not start. You can retry this turn."),
      ).toBeNull();
    },
  );

  it.each(["classic", "beta"] as const)(
    "%s ignores duplicated prepared media and retries a failed media ticket once",
    async (kind) => {
      const initial = detail();
      initial.status = "running";
      initial.public_turns = [];
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
      render(
        kind === "beta" ? (
          <BetaDebateStage {...props} />
        ) : (
          <DebateStage {...props} />
        ),
      );
      await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
      act(() => socket.emitOpen());
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
      expect(play).toHaveBeenCalledTimes(1);
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
  it.each(["classic", "beta"] as const)(
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
        return kind === "beta" ? (
          <BetaDebateStage {...props} />
        ) : (
          <DebateStage {...props} />
        );
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
