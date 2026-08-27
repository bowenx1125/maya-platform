import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AvatarConfig } from "../components/avatar";
import type {
  DebatePlaybackApi,
  PlaybackSocket,
} from "../components/debate/stage";
import type { DebateDetail, DebatePlaybackState } from "../lib/api";
import {
  DebateStage,
  consumeEventSequence,
  deriveAvatarStates,
  parsePlaybackEvent,
  visibleTurnFromPlaybackStarted,
} from "../components/debate/stage";

vi.mock("../components/avatar/avatar-preview", () => ({
  AvatarPreview: ({
    fallbackLabel,
    state,
  }: {
    fallbackLabel?: string;
    state?: string;
  }) => (
    <div data-avatar-state={state ?? "idle"}>{fallbackLabel ?? "avatar"}</div>
  ),
}));

const debateId = "20000000-0000-4000-8000-000000000001";
const turnId = "40000000-0000-4000-8000-000000000001";
const nextTurnId = "40000000-0000-4000-8000-000000000002";
const participantAId = "30000000-0000-4000-8000-000000000001";
const participantBId = "30000000-0000-4000-8000-000000000002";
const epoch = "50000000-0000-4000-8000-000000000001";
const mediaUrl = `/api/v1/debates/${debateId}/audio/${turnId}?media_ticket=${"A".repeat(43)}`;

const avatarConfig: AvatarConfig = {
  template_id: "wave1-default-head",
  material_theme: "demo",
  eye_color: null,
  default_expression: "neutral",
  expression_strength: "medium",
  motion_style: "calm",
};

function detail(
  overrides: Partial<
    Pick<DebateDetail, "status" | "public_turns" | "last_sequence">
  > = {},
): DebateDetail {
  return {
    id: debateId,
    course_id: "10000000-0000-4000-8000-000000000001",
    topic: "Should the United States ban TikTok's recommendation algorithm?",
    status: overrides.status ?? "running",
    created_at: "2026-08-27T00:00:00Z",
    revision: 1,
    last_sequence: overrides.last_sequence ?? 0,
    rule_set_id: "ordered_multi_agent_rounds_demo_v1",
    participants: [
      {
        id: participantAId,
        slot: "A",
        order_index: 0,
        agent_id: "60000000-0000-4000-8000-000000000001",
        agent_name: "Bowen",
        agent_version_id: "70000000-0000-4000-8000-000000000001",
        version_label: "V1.0",
        knowledge_snapshot_id: "80000000-0000-4000-8000-000000000001",
        avatar_config: avatarConfig,
        effective_voice_profile_id: null,
        voice_fallback_active: true,
        stance_mode: "assigned",
        initial_stance: "support",
        current_stance: "support",
      },
      {
        id: participantBId,
        slot: "B",
        order_index: 1,
        agent_id: "60000000-0000-4000-8000-000000000002",
        agent_name: "KaiKai",
        agent_version_id: "70000000-0000-4000-8000-000000000002",
        version_label: "V1.0",
        knowledge_snapshot_id: "80000000-0000-4000-8000-000000000002",
        avatar_config: avatarConfig,
        effective_voice_profile_id: null,
        voice_fallback_active: true,
        stance_mode: "assigned",
        initial_stance: "oppose",
        current_stance: "oppose",
      },
    ],
    public_turns: overrides.public_turns ?? [],
    playback: {
      status: "preparing",
      mode: "live",
      current_turn_id: turnId,
      cursor_ms: 0,
      playback_rate: 1,
      control_version: 0,
      next_turn_ready: false,
    },
    interaction_status: "closed",
    insight_status: "not_started",
    report_status: "not_started",
  };
}

type Listener = (event: Event) => void;

class TestSocket implements PlaybackSocket {
  readonly sent: string[] = [];
  readonly closed = vi.fn();
  private readonly listeners = new Map<string, Set<Listener>>();

  send(data: string): void {
    this.sent.push(data);
  }

  close(code?: number, reason?: string): void {
    this.closed(code, reason);
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

  emit(type: "open" | "close" | "error" | "message", value?: unknown): void {
    const event =
      type === "message"
        ? new MessageEvent(type, { data: JSON.stringify(value) })
        : new Event(type);
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }

  commands(): Record<string, unknown>[] {
    return this.sent.map((item) => JSON.parse(item) as Record<string, unknown>);
  }
}

function fakeApi(
  initial: DebateDetail,
): DebatePlaybackApi & { pauseDebate: ReturnType<typeof vi.fn> } {
  const paused = {
    ...initial.playback,
    status: "paused" as const,
    control_version: initial.playback.control_version + 1,
  };
  return {
    startDebate: vi.fn().mockResolvedValue(initial),
    pauseDebate: vi.fn().mockResolvedValue(paused),
    resumeDebate: vi
      .fn()
      .mockResolvedValue({ ...initial.playback, status: "ready" }),
    skipDebateTurn: vi
      .fn()
      .mockResolvedValue({ ...initial.playback, status: "preparing" }),
    advanceDebatePlayback: vi.fn().mockResolvedValue({
      ...initial.playback,
      status: "ready",
      current_turn_id: nextTurnId,
      next_turn_ready: false,
      control_version: initial.playback.control_version + 1,
    }),
    stopDebate: vi.fn().mockResolvedValue({
      ...initial,
      status: "stopped",
      playback: { ...initial.playback, status: "stopped" },
    }),
    replayDebate: vi.fn().mockResolvedValue({
      ...initial.playback,
      mode: "replay",
      status: "ready",
    }),
    replayDebateTurn: vi.fn().mockResolvedValue({
      ...initial.playback,
      mode: "replay",
      status: "ready",
    }),
  } as DebatePlaybackApi & { pauseDebate: ReturnType<typeof vi.fn> };
}

function envelope(
  eventType: string,
  sequence: number,
  payload: Record<string, unknown>,
) {
  return {
    event_id: `90000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
    event_type: eventType,
    event_version: 1,
    debate_id: debateId,
    sequence,
    occurred_at: "2026-08-27T00:00:00Z",
    payload,
  };
}

function snapshotPayload(
  playback: DebateDetail["playback"] = detail().playback,
) {
  return {
    debate_status: "running",
    playback_status: playback.status,
    interaction_status: "closed",
    insight_status: "not_started",
    report_status: "not_started",
    public_turns: [],
    playback,
    interaction: {
      status: "closed",
      votes: [],
      barrage_count: 0,
      total_votes: 0,
      public_url: null,
    },
    report: {
      generation_status: "not_started",
      latest_attempt_status: "not_started",
      insight: {
        status: "not_started",
        included_count: 0,
        filtered_count: 0,
        items: [],
      },
      active_revision_id: null,
      current_success_revision: null,
    },
    latest_sequence: 0,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Wave 2 M12 playback stage", () => {
  it("does not acquire a controller for a draft, then reacquires after start", async () => {
    const initial = detail({ status: "draft" });
    const started = { ...initial, status: "running" as const };
    const socket = new TestSocket();
    const api = fakeApi(initial);
    api.startDebate = vi.fn().mockResolvedValue(started);
    render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );

    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(
      socket
        .commands()
        .some(
          (command) => command.command_type === "playback.controller.acquire",
        ),
    ).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Start debate" }));
    await waitFor(() =>
      expect(
        socket
          .commands()
          .some(
            (command) => command.command_type === "playback.controller.acquire",
          ),
      ).toBe(true),
    );
  });

  it("reacquires after a stale start response when live turn events won the race", async () => {
    const initial = detail({ status: "draft" });
    initial.playback.current_turn_id = null;
    const started = {
      ...initial,
      status: "running" as const,
      playback: { ...initial.playback, current_turn_id: null },
    };
    const socket = new TestSocket();
    const api = fakeApi(initial);
    let resolveStart!: (value: DebateDetail) => void;
    api.startDebate = vi.fn().mockReturnValue(
      new Promise<DebateDetail>((resolve) => {
        resolveStart = resolve;
      }),
    );
    render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );

    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    fireEvent.click(screen.getByRole("button", { name: "Start debate" }));

    socket.emit(
      "message",
      envelope("turn.preparing", 1, {
        turn_id: turnId,
        slot: "A",
        round_no: 1,
        stage: "rag",
      }),
    );
    socket.emit(
      "message",
      envelope("turn.ready", 2, {
        turn_id: turnId,
        slot: "A",
        round_no: 1,
        audio_ready: true,
        retrieval_status: "no_match",
        grounding_mode: "general_reasoning",
        audio_duration_ms: 1000,
      }),
    );
    await waitFor(() =>
      expect(
        document.querySelector('[data-playback-status="ready"]'),
      ).toBeTruthy(),
    );

    resolveStart(started);
    await waitFor(() =>
      expect(
        socket
          .commands()
          .filter(
            (command) => command.command_type === "playback.controller.acquire",
          ),
      ).toHaveLength(1),
    );
    expect(
      screen.getByText("Waiting for the teacher controller…"),
    ).toBeTruthy();
    expect(
      socket
        .commands()
        .filter((command) => command.command_type === "playback.media.prepare"),
    ).toHaveLength(0);
  });

  it.each([
    ["debate.failed", "failed", "Debate needs attention"],
    ["debate.stopped", "stopped", "Debate stopped"],
  ] as const)(
    "does not reacquire after a stale start response when %s wins the race",
    async (terminalEvent, outcome, expectedLabel) => {
      const initial = detail({ status: "draft" });
      initial.playback.current_turn_id = null;
      const started = {
        ...initial,
        status: "running" as const,
        playback: { ...initial.playback, current_turn_id: null },
      };
      const socket = new TestSocket();
      const api = fakeApi(initial);
      let resolveStart!: (value: DebateDetail) => void;
      api.startDebate = vi.fn().mockReturnValue(
        new Promise<DebateDetail>((resolve) => {
          resolveStart = resolve;
        }),
      );
      render(
        <DebateStage
          api={api}
          debateId={debateId}
          detail={initial}
          socketFactory={() => socket}
        />,
      );

      await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
      socket.emit("open");
      fireEvent.click(screen.getByRole("button", { name: "Start debate" }));
      socket.emit(
        "message",
        envelope("turn.preparing", 1, {
          turn_id: turnId,
          slot: "A",
          round_no: 1,
          stage: "rag",
        }),
      );
      socket.emit(
        "message",
        envelope(terminalEvent, 2, {
          final_states: {},
          downstream_outcome: outcome,
        }),
      );

      await waitFor(() =>
        expect(screen.getAllByText(expectedLabel).length).toBeGreaterThan(0),
      );
      resolveStart(started);
      await new Promise((resolve) => window.setTimeout(resolve, 0));
      expect(
        socket
          .commands()
          .filter(
            (command) => command.command_type === "playback.controller.acquire",
          ),
      ).toHaveLength(0);
      expect(
        document.querySelector('[data-playback-status="stopped"]'),
      ).toBeTruthy();
    },
  );

  it("waits for teacher Next after skip and uses the next media action", async () => {
    const initial = detail({
      public_turns: [
        {
          id: turnId,
          participant_id: participantAId,
          round_no: 1,
          turn_index: 0,
          speech: "The first public speech.",
          retrieval_status: "matched",
          grounding_mode: "mixed",
          sources: [],
        },
      ],
    });
    const socket = new TestSocket();
    const api = fakeApi(initial);
    api.resumeDebate = vi.fn().mockResolvedValue({
      ...initial.playback,
      status: "ready",
      current_turn_id: turnId,
      control_version: 2,
    });
    api.skipDebateTurn = vi.fn().mockResolvedValue({
      ...initial.playback,
      status: "waiting_next",
      current_turn_id: turnId,
      control_version: 3,
      next_turn_ready: false,
    });
    api.advanceDebatePlayback = vi.fn().mockResolvedValue({
      ...initial.playback,
      status: "ready",
      current_turn_id: nextTurnId,
      control_version: 4,
      next_turn_ready: false,
    });
    render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );

    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit(
      "message",
      envelope("playback.paused", 1, {
        turn_id: turnId,
        cursor_ms: 200,
        control_version: 1,
        playback_rate: 1,
      }),
    );
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000030",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000030",
      controller_epoch: epoch,
      control_version: 1,
    });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Resume" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    await waitFor(() =>
      expect(
        socket
          .commands()
          .some(
            (command) =>
              command.command_type === "playback.media.prepare" &&
              command.turn_id === turnId &&
              command.playback_action === "resume",
          ),
      ).toBe(true),
    );
    socket.emit(
      "message",
      envelope("playback.resumed", 2, {
        turn_id: turnId,
        cursor_ms: 200,
        control_version: 2,
        playback_rate: 1,
      }),
    );
    socket.emit(
      "message",
      envelope("playback.started", 3, {
        turn_id: turnId,
        slot: "A",
        round_no: 1,
        speech: "The first public speech.",
        sources: [{ source_filename: "first.md" }],
        playback_url: `/api/v1/debates/${debateId}/audio/${turnId}`,
        cursor_ms: 0,
        playback_rate: 1,
        avatar_states: [],
      }),
    );

    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "Skip current turn" })
          .hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Skip current turn" }));
    await waitFor(() => expect(api.skipDebateTurn).toHaveBeenCalled());
    socket.emit(
      "message",
      envelope("playback.skipped", 4, {
        turn_id: turnId,
        cursor_ms: 0,
        control_version: 3,
        playback_rate: 1,
      }),
    );
    socket.emit(
      "message",
      envelope("playback.waiting_next", 5, {
        completed_turn_id: turnId,
        control_version: 3,
        next_turn_ready: false,
      }),
    );
    expect(screen.getAllByText("The first public speech.")).not.toHaveLength(0);
    expect(
      screen.getByRole("button", { name: "Next / 下一步" }),
    ).toHaveProperty("disabled", true);

    // A hidden successor may be ready, but turn.ready never unlocks or
    // prepares it. Only the readiness-change waiting event does.
    socket.emit(
      "message",
      envelope("turn.ready", 6, {
        turn_id: nextTurnId,
        slot: "B",
        round_no: 1,
        audio_ready: true,
        retrieval_status: "no_match",
        grounding_mode: "general_reasoning",
        audio_duration_ms: 1000,
      }),
    );

    expect(
      socket
        .commands()
        .filter(
          (command) =>
            command.command_type === "playback.media.prepare" &&
            command.turn_id === nextTurnId,
        ),
    ).toHaveLength(0);
    socket.emit(
      "message",
      envelope("playback.waiting_next", 7, {
        completed_turn_id: turnId,
        control_version: 3,
        next_turn_ready: true,
      }),
    );
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "Next / 下一步" })
          .hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Next / 下一步" }));
    await waitFor(() =>
      expect(api.advanceDebatePlayback).toHaveBeenCalledWith(debateId, {
        expected_control_version: 3,
        expected_current_turn_id: turnId,
      }),
    );
    await waitFor(() => {
      const nextPrepare = socket
        .commands()
        .filter(
          (command) =>
            command.command_type === "playback.media.prepare" &&
            command.turn_id === nextTurnId,
        );
      expect(nextPrepare).toHaveLength(1);
      expect(nextPrepare[0]?.playback_action).toBe("next");
    });
  });

  it("ignores a delayed pause response after the live item advances to the next turn", async () => {
    const initial = detail({
      last_sequence: 4,
      public_turns: [
        {
          id: turnId,
          participant_id: participantAId,
          round_no: 1,
          turn_index: 0,
          speech: "A public speech before the control race.",
          retrieval_status: "matched",
          grounding_mode: "mixed",
          sources: [],
        },
      ],
    });
    initial.playback = {
      ...initial.playback,
      status: "playing",
      control_version: 5,
    };
    const socket = new TestSocket();
    const api = fakeApi(initial);
    let resolvePause!: (state: DebatePlaybackState) => void;
    api.pauseDebate = vi.fn().mockReturnValue(
      new Promise<DebatePlaybackState>((resolve) => {
        resolvePause = resolve;
      }),
    );
    render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );

    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000050",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000050",
      controller_epoch: epoch,
      control_version: 5,
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Pause" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(api.pauseDebate).toHaveBeenCalledWith(debateId, 5);

    socket.emit(
      "message",
      envelope("playback.paused", 5, {
        turn_id: turnId,
        cursor_ms: 300,
        control_version: 6,
        playback_rate: 1,
      }),
    );
    socket.emit(
      "message",
      envelope("playback.resumed", 6, {
        turn_id: turnId,
        cursor_ms: 300,
        control_version: 7,
        playback_rate: 1,
      }),
    );
    socket.emit(
      "message",
      envelope("playback.skipped", 7, {
        turn_id: turnId,
        cursor_ms: 300,
        control_version: 8,
        playback_rate: 1,
      }),
    );
    socket.emit(
      "message",
      envelope("playback.waiting_next", 8, {
        completed_turn_id: turnId,
        control_version: 8,
        next_turn_ready: false,
      }),
    );
    socket.emit(
      "message",
      envelope("turn.ready", 9, {
        turn_id: nextTurnId,
        slot: "B",
        round_no: 1,
        audio_ready: true,
        retrieval_status: "no_match",
        grounding_mode: "general_reasoning",
        audio_duration_ms: 1000,
      }),
    );
    socket.emit(
      "message",
      envelope("playback.waiting_next", 10, {
        completed_turn_id: turnId,
        control_version: 8,
        next_turn_ready: true,
      }),
    );
    // A late A event cannot roll the committed waiting state back while the
    // in-flight pause response remains unresolved.
    socket.emit(
      "message",
      envelope("playback.paused", 11, {
        turn_id: turnId,
        cursor_ms: 400,
        control_version: 10,
        playback_rate: 1,
      }),
    );
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000051",
      message_type: "controller.revoked",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      controller_epoch: "50000000-0000-4000-8000-000000000002",
      reason: "superseded",
    });
    await waitFor(() =>
      expect(
        document.querySelector('[data-playback-status="waiting_next"]'),
      ).toBeTruthy(),
    );

    resolvePause({
      ...initial.playback,
      status: "paused",
      current_turn_id: turnId,
      control_version: 8,
      next_turn_ready: false,
    });
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(
      document.querySelector('[data-playback-status="waiting_next"]'),
    ).toBeTruthy();
    expect(api.pauseDebate).toHaveBeenCalledTimes(1);
  });

  it("clears local audio and avatar state when the controller is revoked", async () => {
    const initial = detail();
    const socket = new TestSocket();
    const api = fakeApi(initial);
    const { container } = render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );

    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit("message", {
      message_id: "91000000-0000-0000-8000-000000000019",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-0000-8000-000000000019",
      controller_epoch: epoch,
      control_version: 0,
    });
    const audio = container.querySelector("audio") as HTMLAudioElement;
    audio.src = mediaUrl;
    socket.emit("message", {
      message_id: "91000000-0000-0000-8000-000000000020",
      message_type: "controller.revoked",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      controller_epoch: epoch,
      reason: "start_next",
    });

    await waitFor(() => expect(audio.getAttribute("src")).toBeNull());
    expect(
      document.querySelector('[data-connection="disconnected"]'),
    ).toBeTruthy();
    expect(
      Array.from(container.querySelectorAll("[data-avatar-state]")).every(
        (item) => item.getAttribute("data-avatar-state") === "idle",
      ),
    ).toBe(true);
  });

  it.each(["replay-all", "replay-turn"] as const)(
    "waits for controller acquisition before dispatching %s",
    async (replayKind) => {
      const initial = detail({
        status: "completed",
        public_turns: [
          {
            id: turnId,
            participant_id: participantAId,
            round_no: 1,
            turn_index: 0,
            speech: "A published speech available for replay.",
            retrieval_status: "matched",
            grounding_mode: "mixed",
            sources: [],
          },
        ],
      });
      initial.playback = {
        ...initial.playback,
        status: "completed",
        mode: "live",
        current_turn_id: null,
        control_version: 0,
      };
      const replayState = {
        ...initial.playback,
        status: "ready" as const,
        mode: "replay" as const,
        current_turn_id: turnId,
        control_version: 1,
      };
      const socket = new TestSocket();
      const api = fakeApi(initial);
      api.replayDebate = vi.fn().mockResolvedValue(replayState);
      api.replayDebateTurn = vi.fn().mockResolvedValue(replayState);
      render(
        <DebateStage
          api={api}
          debateId={debateId}
          detail={initial}
          socketFactory={() => socket}
        />,
      );

      await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
      socket.emit("open");
      const replayButton =
        replayKind === "replay-all"
          ? screen.getByRole("button", { name: "Replay all" })
          : screen.getAllByRole("button", { name: "Replay turn" })[0];
      expect(replayButton).toBeDefined();
      expect((replayButton as HTMLButtonElement).disabled).toBe(true);
      fireEvent.click(replayButton as HTMLElement);
      expect(api.replayDebate).not.toHaveBeenCalled();
      expect(api.replayDebateTurn).not.toHaveBeenCalled();

      socket.emit("message", {
        message_id: "91000000-0000-4000-8000-000000000061",
        message_type: "controller.acquired",
        result_version: 1,
        debate_id: debateId,
        occurred_at: "2026-08-27T00:00:00Z",
        command_id: "92000000-0000-4000-8000-000000000061",
        controller_epoch: epoch,
        control_version: 0,
      });
      await waitFor(() =>
        expect((replayButton as HTMLButtonElement).disabled).toBe(false),
      );
      fireEvent.click(replayButton as HTMLElement);

      if (replayKind === "replay-all") {
        await waitFor(() =>
          expect(api.replayDebate).toHaveBeenCalledWith(debateId, 0),
        );
      } else {
        await waitFor(() =>
          expect(api.replayDebateTurn).toHaveBeenCalledWith(
            debateId,
            turnId,
            0,
          ),
        );
      }
      await waitFor(() => {
        const prepareCommands = socket
          .commands()
          .filter(
            (command) =>
              command.command_type === "playback.media.prepare" &&
              command.turn_id === turnId,
          );
        expect(prepareCommands).toHaveLength(1);
        expect(prepareCommands[0]?.controller_epoch).toBe(epoch);
        expect(prepareCommands[0]?.playback_action).toBe("replay");
      });
      expect(
        socket
          .commands()
          .filter(
            (command) => command.command_type === "playback.controller.acquire",
          ),
      ).toHaveLength(1);
    },
  );

  it("does not loop a completed full replay back into media preparation", async () => {
    const initial = detail({
      status: "debate_finished",
      public_turns: [
        {
          id: turnId,
          participant_id: participantAId,
          round_no: 1,
          turn_index: 0,
          speech: "A published speech",
          retrieval_status: "matched",
          grounding_mode: "mixed",
          sources: [],
        },
      ],
    });
    initial.playback.mode = "replay";
    initial.playback.status = "playing";
    const socket = new TestSocket();
    const api = fakeApi(initial);
    render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );

    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit(
      "message",
      envelope("replay.completed", 1, {
        scope: "all",
        turn_id: turnId,
        control_version: 2,
      }),
    );
    await waitFor(() =>
      expect(screen.getByText("Debate complete")).toBeTruthy(),
    );
    expect(
      socket
        .commands()
        .filter((command) => command.command_type === "playback.media.prepare"),
    ).toHaveLength(0);
  });

  it("uses the authoritative snapshot to continue an intermediate full replay", async () => {
    const firstPublicTurn = {
      id: turnId,
      participant_id: participantAId,
      round_no: 1,
      turn_index: 0,
      speech: "The first public speech.",
      retrieval_status: "matched" as const,
      grounding_mode: "mixed" as const,
      sources: [],
    };
    const secondPublicTurn = {
      ...firstPublicTurn,
      id: nextTurnId,
      participant_id: participantBId,
      turn_index: 1,
      speech: "The second public speech.",
    };
    const initial = detail({
      status: "debate_finished",
      public_turns: [firstPublicTurn, secondPublicTurn],
    });
    initial.playback = {
      ...initial.playback,
      status: "playing",
      mode: "replay",
      current_turn_id: turnId,
      control_version: 1,
    };
    const intermediate = {
      ...initial,
      last_sequence: 1,
      playback: {
        ...initial.playback,
        status: "ready" as const,
        mode: "replay" as const,
        current_turn_id: nextTurnId,
        control_version: 2,
      },
    };
    const final = {
      ...intermediate,
      last_sequence: 2,
      playback: {
        ...intermediate.playback,
        status: "completed" as const,
        current_turn_id: nextTurnId,
        control_version: 3,
      },
    };
    const refreshSnapshot = vi
      .fn()
      .mockResolvedValueOnce(intermediate)
      .mockResolvedValueOnce(final);
    const socket = new TestSocket();
    render(
      <DebateStage
        api={fakeApi(initial)}
        debateId={debateId}
        detail={initial}
        refreshSnapshot={refreshSnapshot}
        socketFactory={() => socket}
      />,
    );

    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000040",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000040",
      controller_epoch: epoch,
      control_version: 1,
    });

    socket.emit(
      "message",
      envelope("replay.completed", 1, {
        scope: "all",
        turn_id: turnId,
        control_version: 2,
      }),
    );
    await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1));
    await waitFor(() => {
      const prepareCommands = socket
        .commands()
        .filter((command) => command.command_type === "playback.media.prepare");
      expect(prepareCommands).toHaveLength(1);
      expect(prepareCommands[0]?.turn_id).toBe(nextTurnId);
      expect(prepareCommands[0]?.playback_action).toBe("replay");
    });

    socket.emit(
      "message",
      envelope("replay.completed", 2, {
        scope: "all",
        turn_id: nextTurnId,
        control_version: 3,
      }),
    );
    await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        document.querySelector('[data-playback-status="completed"]'),
      ).toBeTruthy(),
    );
    expect(
      socket
        .commands()
        .filter((command) => command.command_type === "playback.media.prepare"),
    ).toHaveLength(1);
  });

  it("keeps one socket when static locale labels change", async () => {
    const initial = detail();
    const socket = new TestSocket();
    const socketFactory = vi.fn(() => socket);
    const { rerender: rerenderStage } = render(
      <DebateStage
        api={fakeApi(initial)}
        debateId={debateId}
        detail={initial}
        socketFactory={socketFactory}
        labels={{ stageTitle: "English stage" }}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    rerenderStage(
      <DebateStage
        api={fakeApi(initial)}
        debateId={debateId}
        detail={initial}
        socketFactory={socketFactory}
        labels={{ stageTitle: "中文舞台" }}
      />,
    );
    expect(socketFactory).toHaveBeenCalledTimes(1);
  });

  it("keeps turn.ready private and only reveals speech at playback.started", async () => {
    const initial = detail();
    const socket = new TestSocket();
    const api = fakeApi(initial);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const { container } = render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );

    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit("message", {
      ...envelope("snapshot", 0, snapshotPayload()),
      payload: snapshotPayload(),
    });
    socket.emit("message", {
      ...envelope("turn.ready", 1, {
        turn_id: turnId,
        slot: "A",
        round_no: 1,
        audio_ready: true,
        retrieval_status: "matched",
        speech: "SECRET_PREPARED_SPEECH",
      }),
    });

    expect(screen.queryByText("SECRET_PREPARED_SPEECH")).toBeNull();
    await waitFor(() =>
      expect(
        socket
          .commands()
          .some(
            (command) => command.command_type === "playback.controller.acquire",
          ),
      ).toBe(true),
    );

    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000001",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000001",
      controller_epoch: epoch,
      control_version: 1,
    });
    await waitFor(() =>
      expect(
        socket
          .commands()
          .some((command) => command.command_type === "playback.media.prepare"),
      ).toBe(true),
    );
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000002",
      message_type: "media.prepared",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000002",
      controller_epoch: epoch,
      turn_id: turnId,
      media_url: mediaUrl,
      expires_at: "2026-08-27T00:01:00Z",
    });
    await waitFor(() =>
      expect(
        socket
          .commands()
          .some((command) => command.command_type === "playback.started_ack"),
      ).toBe(true),
    );

    socket.emit("message", {
      ...envelope("playback.started", 2, {
        turn_id: turnId,
        slot: "A",
        round_no: 1,
        speech: "PUBLIC_SPEECH_AFTER_ACK",
        sources: [{ source_filename: "evidence.md" }],
        playback_url: `/api/v1/debates/${debateId}/audio/${turnId}`,
        cursor_ms: 0,
        playback_rate: 1,
        avatar_states: [
          {
            participant_id: participantAId,
            slot: "A",
            motion_state: "speaking",
            expression: "neutral",
            expression_strength: "medium",
          },
          {
            participant_id: participantBId,
            slot: "B",
            motion_state: "listening",
            expression: "attentive",
            expression_strength: "medium",
          },
        ],
      }),
    });

    expect(
      await screen.findAllByText("PUBLIC_SPEECH_AFTER_ACK"),
    ).not.toHaveLength(0);
    expect(screen.getByText("evidence.md")).toBeTruthy();
    expect(container.querySelectorAll("audio")).toHaveLength(1);
  });

  it("restores the public current speech card from a playing snapshot", async () => {
    const initial = detail();
    const socket = new TestSocket();
    const { container } = render(
      <DebateStage
        api={fakeApi(initial)}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    const playing = {
      ...initial.playback,
      status: "playing" as const,
      current_turn_id: turnId,
      control_version: 4,
    };
    socket.emit(
      "message",
      envelope("snapshot", 0, {
        ...snapshotPayload(playing),
        latest_sequence: 4,
        public_turns: [
          {
            id: turnId,
            participant_id: participantAId,
            round_no: 1,
            turn_index: 0,
            speech: "Recovered public speech after refresh",
            retrieval_status: "matched",
            grounding_mode: "mixed",
            sources: [{ source_filename: "refresh-evidence.md" }],
          },
        ],
      }),
    );

    expect(
      await screen.findAllByText("Recovered public speech after refresh"),
    ).not.toHaveLength(0);
    expect(screen.getByText("refresh-evidence.md")).toBeTruthy();
    expect(
      container.querySelector(`[data-motion-state="speaking"]`),
    ).toBeTruthy();
  });

  it("keeps Stop disabled after the debate finishes, including replay", () => {
    const finished = detail({
      status: "debate_finished",
      public_turns: [
        {
          id: turnId,
          participant_id: participantAId,
          round_no: 1,
          turn_index: 0,
          speech: "A completed public speech",
          retrieval_status: "matched",
          grounding_mode: "mixed",
          sources: [],
        },
      ],
    });
    finished.playback = {
      ...finished.playback,
      status: "completed",
      current_turn_id: null,
    };
    const { rerender } = render(
      <DebateStage
        api={fakeApi(finished)}
        debateId={debateId}
        detail={finished}
        socketFactory={() => new TestSocket()}
      />,
    );
    expect(
      (screen.getByRole("button", { name: "Stop debate" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    const replaying = {
      ...finished,
      playback: {
        ...finished.playback,
        status: "playing" as const,
        mode: "replay" as const,
        current_turn_id: turnId,
      },
    };
    rerender(
      <DebateStage
        api={fakeApi(replaying)}
        debateId={debateId}
        detail={replaying}
        socketFactory={() => new TestSocket()}
      />,
    );
    expect(
      (screen.getByRole("button", { name: "Stop debate" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("pauses locally without selecting a new turn and recovers a sequence gap", async () => {
    const initial = detail({
      status: "running",
      last_sequence: 0,
      public_turns: [
        {
          id: turnId,
          participant_id: participantAId,
          round_no: 1,
          turn_index: 0,
          speech: "A published speech",
          retrieval_status: "matched",
          grounding_mode: "mixed",
          sources: [],
        },
      ],
    });
    initial.playback.status = "playing";
    const socket = new TestSocket();
    const api = fakeApi(initial);
    render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() =>
      expect(api.pauseDebate).toHaveBeenCalledWith(debateId, 0),
    );
    expect(screen.getByRole("button", { name: "Resume" })).toBeTruthy();
    expect(initial.public_turns[0]?.id).toBe(turnId);

    socket.emit(
      "message",
      envelope("playback.started", 2, {
        turn_id: turnId,
        speech: "gap test",
        sources: [],
        playback_url: `/api/v1/debates/${debateId}/audio/${turnId}`,
        cursor_ms: 0,
        avatar_states: [],
      }),
    );
    await waitFor(() => expect(socket.closed).toHaveBeenCalled());
    expect(
      document.querySelector('[data-connection="reconnecting"]'),
    ).toBeTruthy();
  });

  it("sends ended acknowledgement only from the native audio ended event", async () => {
    const initial = detail();
    const socket = new TestSocket();
    const api = fakeApi(initial);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const { container } = render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit("message", envelope("snapshot", 0, snapshotPayload()));
    socket.emit(
      "message",
      envelope("turn.ready", 1, {
        turn_id: turnId,
        slot: "A",
        round_no: 1,
        audio_ready: true,
        retrieval_status: "no_match",
      }),
    );
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000003",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000003",
      controller_epoch: epoch,
      control_version: 1,
    });
    await waitFor(() =>
      expect(
        socket
          .commands()
          .some((command) => command.command_type === "playback.media.prepare"),
      ).toBe(true),
    );
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000004",
      message_type: "media.prepared",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000004",
      controller_epoch: epoch,
      turn_id: turnId,
      media_url: mediaUrl,
      expires_at: "2026-08-27T00:01:00Z",
    });
    await waitFor(() =>
      expect(
        socket
          .commands()
          .some((command) => command.command_type === "playback.started_ack"),
      ).toBe(true),
    );
    socket.emit(
      "message",
      envelope("playback.started", 2, {
        turn_id: turnId,
        slot: "A",
        speech: "Public",
        sources: [],
        playback_url: `/api/v1/debates/${debateId}/audio/${turnId}`,
        cursor_ms: 0,
        avatar_states: [],
      }),
    );
    fireEvent.ended(container.querySelector("audio") as HTMLAudioElement);
    await waitFor(() =>
      expect(
        socket
          .commands()
          .some((command) => command.command_type === "playback.ended_ack"),
      ).toBe(true),
    );
    socket.emit(
      "message",
      envelope("playback.waiting_next", 3, {
        completed_turn_id: turnId,
        control_version: 1,
        next_turn_ready: false,
      }),
    );
    await waitFor(() =>
      expect(
        document.querySelector('[data-playback-status="waiting_next"]'),
      ).toBeTruthy(),
    );
    expect(
      socket
        .commands()
        .filter((command) => command.command_type === "playback.media.prepare"),
    ).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Next / 下一步" }),
    ).toHaveProperty("disabled", true);
  });

  it("enables bilingual Next only for live ready waiting state and locks while busy", async () => {
    const initial = detail();
    initial.playback = {
      ...initial.playback,
      status: "waiting_next",
      mode: "live",
      current_turn_id: turnId,
      next_turn_ready: false,
    };
    const socket = new TestSocket();
    const api = fakeApi(initial);
    let resolveNext!: (value: DebatePlaybackState) => void;
    api.advanceDebatePlayback = vi.fn().mockReturnValue(
      new Promise<DebatePlaybackState>((resolve) => {
        resolveNext = resolve;
      }),
    );
    render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );

    const nextButton = screen.getByRole("button", {
      name: "Next / 下一步",
    }) as HTMLButtonElement;
    expect(nextButton.disabled).toBe(true);
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000080",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000080",
      controller_epoch: epoch,
      control_version: 0,
    });
    expect(nextButton.disabled).toBe(true);

    socket.emit(
      "message",
      envelope("playback.waiting_next", 1, {
        completed_turn_id: turnId,
        control_version: 0,
        next_turn_ready: true,
      }),
    );
    await waitFor(() => expect(nextButton.disabled).toBe(false));
    fireEvent.click(nextButton);
    expect(api.advanceDebatePlayback).toHaveBeenCalledWith(debateId, {
      expected_control_version: 0,
      expected_current_turn_id: turnId,
    });
    expect(nextButton.disabled).toBe(true);
    resolveNext({
      ...initial.playback,
      status: "ready",
      mode: "live",
      current_turn_id: nextTurnId,
      control_version: 1,
      next_turn_ready: false,
    });
    await waitFor(() =>
      expect(
        socket
          .commands()
          .filter(
            (command) => command.command_type === "playback.media.prepare",
          ),
      ).toHaveLength(1),
    );
  });

  it("derives next media action from a refreshed ready successor after reconnect", async () => {
    const firstPublicTurn = {
      id: turnId,
      participant_id: participantAId,
      round_no: 1,
      turn_index: 0,
      speech: "The first public speech.",
      retrieval_status: "matched" as const,
      grounding_mode: "mixed" as const,
      sources: [],
    };
    const initial = detail({ public_turns: [firstPublicTurn] });
    initial.playback = {
      ...initial.playback,
      status: "waiting_next",
      current_turn_id: turnId,
      control_version: 3,
      next_turn_ready: true,
    };
    const recovered = {
      ...initial,
      last_sequence: 5,
      playback: {
        ...initial.playback,
        status: "ready" as const,
        current_turn_id: nextTurnId,
        control_version: 4,
        next_turn_ready: false,
      },
    };
    const firstSocket = new TestSocket();
    const secondSocket = new TestSocket();
    const sockets = [firstSocket, secondSocket];
    const socketFactory = vi.fn(() => sockets.shift() as TestSocket);
    const refreshSnapshot = vi.fn().mockResolvedValue(recovered);
    render(
      <DebateStage
        api={fakeApi(initial)}
        debateId={debateId}
        detail={initial}
        refreshSnapshot={refreshSnapshot}
        socketFactory={socketFactory}
      />,
    );

    await waitFor(() => expect(firstSocket.hasListeners("open")).toBe(true));
    firstSocket.emit("open");
    firstSocket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000090",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000090",
      controller_epoch: epoch,
      control_version: 3,
    });
    firstSocket.emit("close");

    await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1), {
      timeout: 2_000,
    });
    await waitFor(() => expect(socketFactory).toHaveBeenCalledTimes(2));
    secondSocket.emit("open");
    secondSocket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000091",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000091",
      controller_epoch: epoch,
      control_version: 4,
    });
    await waitFor(() => {
      const prepare = secondSocket
        .commands()
        .find((command) => command.command_type === "playback.media.prepare");
      expect(prepare?.turn_id).toBe(nextTurnId);
      expect(prepare?.playback_action).toBe("next");
    });
  });

  it("recovers a successor started event after multitab controller revocation", async () => {
    const firstPublicTurn = {
      id: turnId,
      participant_id: participantAId,
      round_no: 1,
      turn_index: 0,
      speech: "The first public speech.",
      retrieval_status: "matched" as const,
      grounding_mode: "mixed" as const,
      sources: [],
    };
    const successorPublicTurn = {
      ...firstPublicTurn,
      id: nextTurnId,
      participant_id: participantBId,
      turn_index: 1,
      speech: "The successor public speech.",
    };
    const initial = detail({
      last_sequence: 3,
      public_turns: [firstPublicTurn],
    });
    initial.playback = {
      ...initial.playback,
      status: "waiting_next",
      current_turn_id: turnId,
      control_version: 3,
      next_turn_ready: true,
    };
    const recovered = {
      ...initial,
      last_sequence: 4,
      public_turns: [firstPublicTurn, successorPublicTurn],
      playback: {
        ...initial.playback,
        status: "playing" as const,
        current_turn_id: nextTurnId,
        control_version: 4,
        next_turn_ready: false,
      },
    };
    const refreshSnapshot = vi.fn().mockResolvedValue(recovered);
    const socket = new TestSocket();
    const api = fakeApi(initial);
    const { container } = render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        refreshSnapshot={refreshSnapshot}
        socketFactory={() => socket}
      />,
    );

    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000092",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000092",
      controller_epoch: epoch,
      control_version: 3,
    });
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000093",
      message_type: "controller.revoked",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      controller_epoch: epoch,
      reason: "superseded",
    });
    socket.emit(
      "message",
      envelope("playback.started", 4, {
        turn_id: nextTurnId,
        slot: "B",
        round_no: 1,
        speech: successorPublicTurn.speech,
        sources: [],
        playback_url: `/api/v1/debates/${debateId}/audio/${nextTurnId}`,
        cursor_ms: 0,
        playback_rate: 1,
        avatar_states: [],
      }),
    );

    await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(
        screen.getAllByText(successorPublicTurn.speech).length,
      ).toBeGreaterThan(0),
    );
    expect(
      container.querySelector('[data-playback-status="playing"]'),
    ).toBeTruthy();
    expect(
      container.querySelector('[data-playback-status="waiting_next"]'),
    ).toBeNull();
  });

  it("holds later events behind the successor recovery watermark", async () => {
    const firstPublicTurn = {
      id: turnId,
      participant_id: participantAId,
      round_no: 1,
      turn_index: 0,
      speech: "The first public speech.",
      retrieval_status: "matched" as const,
      grounding_mode: "mixed" as const,
      sources: [],
    };
    const successorPublicTurn = {
      ...firstPublicTurn,
      id: nextTurnId,
      participant_id: participantBId,
      turn_index: 1,
      speech: "The successor public speech.",
    };
    const initial = detail({
      last_sequence: 3,
      public_turns: [firstPublicTurn],
    });
    initial.playback = {
      ...initial.playback,
      status: "playing",
      current_turn_id: turnId,
      control_version: 3,
    };
    const oldSnapshot = {
      ...initial,
      last_sequence: 4,
      playback: {
        ...initial.playback,
        status: "playing" as const,
        current_turn_id: turnId,
      },
    };
    const recovered = {
      ...initial,
      last_sequence: 5,
      public_turns: [firstPublicTurn, successorPublicTurn],
      playback: {
        ...initial.playback,
        status: "paused" as const,
        current_turn_id: nextTurnId,
        control_version: 4,
      },
    };
    let resolveOldSnapshot!: (value: DebateDetail) => void;
    let resolveRecoveredSnapshot!: (value: DebateDetail) => void;
    const refreshSnapshot = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<DebateDetail>((resolve) => {
            resolveOldSnapshot = resolve;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise<DebateDetail>((resolve) => {
            resolveRecoveredSnapshot = resolve;
          }),
      );
    const latestDetails: DebateDetail[] = [];
    const socket = new TestSocket();
    const { container } = render(
      <DebateStage
        api={fakeApi(initial)}
        debateId={debateId}
        detail={initial}
        onDetailChange={(next) => latestDetails.push(next)}
        refreshSnapshot={refreshSnapshot}
        socketFactory={() => socket}
      />,
    );

    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit(
      "message",
      envelope("playback.started", 4, {
        turn_id: nextTurnId,
        slot: "B",
        round_no: 1,
        speech: successorPublicTurn.speech,
        sources: [],
        playback_url: `/api/v1/debates/${debateId}/audio/${nextTurnId}`,
        cursor_ms: 0,
        playback_rate: 1,
        avatar_states: [],
      }),
    );
    await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1));

    socket.emit(
      "message",
      envelope("playback.paused", 5, {
        turn_id: nextTurnId,
        cursor_ms: 150,
        control_version: 4,
        playback_rate: 1,
      }),
    );
    expect(container.querySelector('[data-playback-status="paused"]')).toBe(
      null,
    );

    resolveOldSnapshot(oldSnapshot);
    await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(2));
    resolveRecoveredSnapshot(recovered);
    await waitFor(() =>
      expect(
        container.querySelector('[data-playback-status="paused"]'),
      ).toBeTruthy(),
    );
    expect(
      container.querySelector('[data-playback-status="playing"]'),
    ).toBeNull();
    expect(latestDetails.at(-1)?.last_sequence).toBe(5);
    expect(latestDetails.at(-1)?.playback.current_turn_id).toBe(nextTurnId);
  });

  it("safely adopts a deterministic successor started event without an HTTP reader", async () => {
    const firstPublicTurn = {
      id: turnId,
      participant_id: participantAId,
      round_no: 1,
      turn_index: 0,
      speech: "The first public speech.",
      retrieval_status: "matched" as const,
      grounding_mode: "mixed" as const,
      sources: [],
    };
    const initial = detail({ public_turns: [firstPublicTurn] });
    initial.playback = {
      ...initial.playback,
      status: "waiting_next",
      current_turn_id: turnId,
      control_version: 3,
      next_turn_ready: true,
    };
    const socket = new TestSocket();
    const successorSpeech = "The safely adopted successor speech.";
    const { container } = render(
      <DebateStage
        api={fakeApi(initial)}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit(
      "message",
      envelope("playback.started", 1, {
        turn_id: nextTurnId,
        slot: "B",
        round_no: 1,
        speech: successorSpeech,
        sources: [],
        playback_url: `/api/v1/debates/${debateId}/audio/${nextTurnId}`,
        cursor_ms: 0,
        playback_rate: 1,
        avatar_states: [],
      }),
    );
    await waitFor(() =>
      expect(screen.getAllByText(successorSpeech).length).toBeGreaterThan(0),
    );
    expect(
      container.querySelector('[data-playback-status="playing"]'),
    ).toBeTruthy();
  });
});

describe("Wave 2 playback protocol helpers", () => {
  it("derives the frozen turn index when a newly public turn was previously hidden", () => {
    const visible = visibleTurnFromPlaybackStarted(detail().participants, [], {
      turn_id: "40000000-0000-4000-8000-000000000004",
      slot: "B",
      round_no: 2,
      speech: "The final public reflection.",
      sources: [],
    });
    expect(visible?.turn_index).toBe(3);
    expect(visible?.participant_id).toBe(participantBId);
  });

  it("maps the server playback state to thinking, attentive listening, and terminal idle", () => {
    const participants = detail().participants;
    const playing = deriveAvatarStates(
      participants,
      {
        status: "playing",
        mode: "live",
        current_turn_id: turnId,
      },
      [],
      participantAId,
    );
    expect(playing.map((item) => item.motion_state)).toEqual([
      "speaking",
      "listening",
    ]);
    expect(playing[1]?.expression).toBe("attentive");

    const preparing = deriveAvatarStates(
      participants,
      {
        status: "ready",
        mode: "live",
        current_turn_id: turnId,
      },
      [],
      participantAId,
    );
    expect(preparing[0]?.motion_state).toBe("thinking");

    const terminal = deriveAvatarStates(
      participants,
      {
        status: "completed",
        mode: "live",
        current_turn_id: turnId,
      },
      [],
      participantAId,
    );
    expect(terminal.every((item) => item.motion_state === "idle")).toBe(true);

    const waiting = deriveAvatarStates(
      participants,
      {
        status: "waiting_next",
        mode: "live",
        current_turn_id: turnId,
      },
      [
        {
          participant_id: participantAId,
          slot: "A",
          motion_state: "speaking",
          expression: "neutral",
          expression_strength: "medium",
        },
      ],
      participantAId,
    );
    expect(waiting.every((item) => item.motion_state !== "speaking")).toBe(
      true,
    );
  });

  it("accepts a snapshot watermark, ignores duplicates, and flags gaps", () => {
    const event = parsePlaybackEvent(
      envelope("playback.started", 4, {
        turn_id: turnId,
        speech: "public",
        sources: [],
        playback_url: `/api/v1/debates/${debateId}/audio/${turnId}`,
        avatar_states: [],
        cursor_ms: 0,
      }),
    );
    expect(event).not.toBeNull();
    expect(consumeEventSequence(0, event!)).toMatchObject({ gap: true });
    expect(consumeEventSequence(4, event!)).toMatchObject({ duplicate: true });
    expect(
      consumeEventSequence(0, {
        event_type: "snapshot",
        sequence: 0,
        payload: { latest_sequence: 4 },
      }),
    ).toMatchObject({ accepted: true, nextSequence: 4 });
    const waiting = parsePlaybackEvent(
      envelope("playback.waiting_next", 1, {
        completed_turn_id: turnId,
        control_version: 8,
        next_turn_ready: true,
      }),
    );
    expect(waiting?.event_type).toBe("playback.waiting_next");
  });
});
