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
import { DebateStage } from "../components/debate/stage";
import type { DebateDetail, DebatePlaybackState } from "../lib/api";

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
const firstTurnId = "40000000-0000-4000-8000-000000000001";
const secondTurnId = "40000000-0000-4000-8000-000000000002";
const participantAId = "30000000-0000-4000-8000-000000000001";
const participantBId = "30000000-0000-4000-8000-000000000002";
const epoch = "50000000-0000-4000-8000-000000000001";

const avatarConfig: AvatarConfig = {
  template_id: "wave1-default-head",
  material_theme: "demo",
  eye_color: null,
  default_expression: "neutral",
  expression_strength: "medium",
  motion_style: "calm",
};

function speech(label: string): string {
  return `${label} public classroom speech.`;
}

function turns() {
  return [
    {
      id: firstTurnId,
      participant_id: participantAId,
      round_no: 1,
      turn_index: 0,
      speech: speech("First"),
      retrieval_status: "matched" as const,
      grounding_mode: "mixed" as const,
      sources: [],
    },
    {
      id: secondTurnId,
      participant_id: participantBId,
      round_no: 1,
      turn_index: 1,
      speech: speech("Second"),
      retrieval_status: "matched" as const,
      grounding_mode: "mixed" as const,
      sources: [],
    },
  ];
}

function detail(
  status: DebateDetail["status"],
  playback: Partial<DebatePlaybackState> = {},
  publicTurns = turns(),
): DebateDetail {
  return {
    id: debateId,
    course_id: "10000000-0000-4000-8000-000000000001",
    topic: "Should the United States ban TikTok's recommendation algorithm?",
    status,
    created_at: "2026-08-28T00:00:00Z",
    revision: 1,
    last_sequence: 0,
    rule_set_id: "ordered_multi_agent_rounds_demo_v1",
    round_count: 2,
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
    public_turns: publicTurns,
    playback: {
      status: "completed",
      mode: "live",
      current_turn_id: null,
      cursor_ms: 0,
      playback_rate: 1,
      control_version: 0,
      next_turn_ready: false,
      ...playback,
    },
    interaction_status: "closed",
    insight_status: "not_started",
    report_status: "not_started",
  };
}

class TestSocket implements PlaybackSocket {
  readonly sent: string[] = [];
  readonly closed = vi.fn();
  private readonly listeners = new Map<string, Set<(event: Event) => void>>();

  send(data: string): void {
    this.sent.push(data);
  }

  close(code?: number, reason?: string): void {
    this.closed(code, reason);
  }

  addEventListener(type: string, listener: (event: Event) => void): void {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: (event: Event) => void): void {
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

function apiFor(
  initial: DebateDetail,
  replay: DebatePlaybackState,
): DebatePlaybackApi {
  return {
    startDebate: vi.fn().mockResolvedValue(initial),
    advanceDebatePlayback: vi.fn().mockResolvedValue(replay),
    replayDebate: vi.fn().mockResolvedValue(replay),
    pauseDebate: vi.fn().mockResolvedValue({ ...replay, status: "paused" }),
    resumeDebate: vi.fn().mockResolvedValue({ ...replay, status: "ready" }),
  };
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
    occurred_at: "2026-08-28T00:00:00Z",
    payload,
  };
}

function acquired(controlVersion: number) {
  return {
    message_id: "91000000-0000-4000-8000-000000000001",
    message_type: "controller.acquired",
    result_version: 1,
    debate_id: debateId,
    occurred_at: "2026-08-28T00:00:00Z",
    command_id: "92000000-0000-4000-8000-000000000001",
    controller_epoch: epoch,
    control_version: controlVersion,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("PW3-D three-control playback", () => {
  it("shows a draft as ready to start rather than in progress", () => {
    const initial = detail(
      "draft",
      {
        status: "preparing",
        mode: "live",
        current_turn_id: null,
      },
      [],
    );
    render(
      <DebateStage
        api={apiFor(initial, initial.playback)}
        debateId={debateId}
        detail={initial}
        socketFactory={() => new TestSocket()}
      />,
    );

    expect(
      document.querySelector('[data-classroom-phase="ready"]'),
    ).toBeTruthy();
    expect(screen.getByText("Ready to start")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start debate" })).toHaveProperty(
      "disabled",
      false,
    );
  });

  it("does not acquire or show reconnect state after an early-finished reload", async () => {
    const initial = detail(
      "debate_finished",
      {
        status: "stopped",
        mode: "live",
        current_turn_id: null,
      },
      [turns()[0]!],
    );
    const socket = new TestSocket();
    render(
      <DebateStage
        api={apiFor(initial, initial.playback)}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");

    expect(
      socket
        .commands()
        .filter(
          (command) => command.command_type === "playback.controller.acquire",
        ),
    ).toHaveLength(0);
    expect(screen.getAllByText("Finished").length).toBeGreaterThan(0);
    expect(screen.queryByText("Debate complete")).toBeNull();
    expect(
      screen.queryByText("Waiting for the teacher controller…"),
    ).toBeNull();
    expect(screen.queryByText("Connection lost")).toBeNull();
    expect(screen.queryByRole("button", { name: "Reconnect" })).toBeNull();
  });

  it("does not acquire or show controller-wait state after a full-finished reload", async () => {
    const initial = detail("completed");
    const socket = new TestSocket();
    render(
      <DebateStage
        api={apiFor(initial, initial.playback)}
        debateId={debateId}
        detail={initial}
        currentAudioDebateId={debateId}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");

    expect(
      socket
        .commands()
        .filter(
          (command) => command.command_type === "playback.controller.acquire",
        ),
    ).toHaveLength(0);
    expect(screen.getAllByText("Finished").length).toBeGreaterThan(0);
    expect(screen.getByText("Debate complete")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Replay whole debate" }),
    ).toHaveProperty("disabled", false);
    expect(
      screen.queryByText("Waiting for the teacher controller…"),
    ).toBeNull();
    expect(screen.queryByText("Connection lost")).toBeNull();
    expect(screen.queryByRole("button", { name: "Reconnect" })).toBeNull();
  });

  it("acquires once on demand before replaying a finished debate", async () => {
    const initial = detail("completed");
    const replayReady: DebatePlaybackState = {
      ...initial.playback,
      status: "ready",
      mode: "replay",
      current_turn_id: firstTurnId,
      control_version: 1,
      next_turn_ready: false,
    };
    const socket = new TestSocket();
    const api = apiFor(initial, replayReady);
    render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        currentAudioDebateId={debateId}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");

    const replay = screen.getByRole("button", {
      name: "Replay whole debate",
    });
    expect(replay).toHaveProperty("disabled", false);
    fireEvent.click(replay);
    // A same-event-loop second click cannot enqueue another acquire or replay.
    fireEvent.click(replay);
    await waitFor(() =>
      expect(
        socket
          .commands()
          .filter(
            (command) => command.command_type === "playback.controller.acquire",
          ),
      ).toHaveLength(1),
    );
    expect(api.replayDebate).not.toHaveBeenCalled();

    socket.emit("message", acquired(0));
    await waitFor(() => expect(api.replayDebate).toHaveBeenCalledTimes(1));
    expect(
      socket
        .commands()
        .filter(
          (command) => command.command_type === "playback.controller.acquire",
        ),
    ).toHaveLength(1);
    expect(screen.getAllByText(speech("First")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(speech("Second")).length).toBeGreaterThan(0);
  });

  it("derives an active replay turn as in progress over a finished debate", () => {
    const initial = detail("completed", {
      status: "playing",
      mode: "replay",
      current_turn_id: firstTurnId,
      control_version: 1,
    });
    render(
      <DebateStage
        api={apiFor(initial, initial.playback)}
        debateId={debateId}
        detail={initial}
        currentAudioDebateId={debateId}
        socketFactory={() => new TestSocket()}
      />,
    );

    expect(
      document.querySelector('[data-classroom-phase="in_progress"]'),
    ).toBeTruthy();
    expect(screen.getByText("In progress")).toBeTruthy();
    expect(
      document.querySelector('[data-motion-state="speaking"]'),
    ).toBeTruthy();
  });

  it("renders exactly Start, Next and Replay Whole Debate", () => {
    const initial = detail("completed");
    render(
      <DebateStage
        api={apiFor(initial, initial.playback)}
        debateId={debateId}
        detail={initial}
        currentAudioDebateId={debateId}
        readOnly={false}
        socketFactory={() => new TestSocket()}
      />,
    );

    expect(screen.getAllByRole("button")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Start debate" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Next" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Replay whole debate" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Skip current turn" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Stop debate" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Replay turn" })).toBeNull();
  });

  it("keeps replay at waiting_next and only prepares after Next", async () => {
    const initial = detail("completed");
    initial.playback = {
      ...initial.playback,
      status: "waiting_next",
      mode: "replay",
      current_turn_id: firstTurnId,
      control_version: 4,
      next_turn_ready: false,
    };
    const replayReady: DebatePlaybackState = {
      ...initial.playback,
      status: "ready",
      mode: "replay",
      current_turn_id: secondTurnId,
      control_version: 5,
      next_turn_ready: false,
    };
    const socket = new TestSocket();
    const api = apiFor(initial, replayReady);
    render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        currentAudioDebateId={debateId}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit("message", acquired(4));
    socket.emit(
      "message",
      envelope("playback.waiting_next", 1, {
        mode: "replay",
        completed_turn_id: firstTurnId,
        control_version: 4,
        next_turn_ready: true,
      }),
    );
    const next = screen.getByRole("button", { name: "Next" });
    await waitFor(() =>
      expect((next as HTMLButtonElement).disabled).toBe(false),
    );
    expect(
      socket
        .commands()
        .filter((command) => command.command_type === "playback.media.prepare"),
    ).toHaveLength(0);

    fireEvent.click(next);
    await waitFor(() => expect(api.advanceDebatePlayback).toHaveBeenCalled());
    await waitFor(() => {
      const prepare = socket
        .commands()
        .filter((command) => command.command_type === "playback.media.prepare");
      expect(prepare).toHaveLength(1);
      expect(prepare[0]?.turn_id).toBe(secondTurnId);
      expect(prepare[0]?.playback_action).toBe("replay");
    });
  });

  it("retains the transcript and renews the controller once after replay", async () => {
    const initial = detail("completed");
    const replayReady: DebatePlaybackState = {
      ...initial.playback,
      status: "ready",
      mode: "replay",
      current_turn_id: firstTurnId,
      control_version: 1,
      next_turn_ready: false,
    };
    const final = detail("completed");
    const refreshSnapshot = vi.fn().mockResolvedValue(final);
    const socket = new TestSocket();
    const api = apiFor(initial, replayReady);
    render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        currentAudioDebateId={debateId}
        refreshSnapshot={refreshSnapshot}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit("message", acquired(0));
    const replay = screen.getByRole("button", {
      name: "Replay whole debate",
    });
    await waitFor(() => expect(replay).toHaveProperty("disabled", false));

    fireEvent.click(replay);
    await waitFor(() => expect(api.replayDebate).toHaveBeenCalled());
    // A replay cursor must not replace the immutable public transcript.
    expect(screen.getAllByText(speech("First")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(speech("Second")).length).toBeGreaterThan(0);

    socket.emit(
      "message",
      envelope("replay.started", 1, {
        scope: "all",
        turn_id: firstTurnId,
        control_version: 1,
      }),
    );
    socket.emit("message", {
      ...acquired(1),
      message_id: "91000000-0000-4000-8000-000000000002",
      message_type: "controller.revoked",
      controller_epoch: epoch,
      reason: "debate_terminal",
    });
    socket.emit(
      "message",
      envelope("replay.completed", 2, {
        scope: "all",
        turn_id: firstTurnId,
        control_version: 2,
      }),
    );

    await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1));
    await waitFor(() => {
      const acquires = socket
        .commands()
        .filter(
          (command) => command.command_type === "playback.controller.acquire",
        );
      expect(acquires).toHaveLength(1);
    });

    // The renewed controller must make a second replay cycle available on
    // the same socket. A second terminal cycle gets exactly one more acquire
    // and never invokes socket.close or a background refresh loop.
    socket.emit("message", acquired(2));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Replay whole debate" }),
      ).toHaveProperty("disabled", false),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Replay whole debate" }),
    );
    await waitFor(() => expect(api.replayDebate).toHaveBeenCalledTimes(2));
    socket.emit(
      "message",
      envelope("replay.started", 3, {
        scope: "all",
        turn_id: firstTurnId,
        control_version: 1,
      }),
    );
    socket.emit("message", {
      ...acquired(2),
      message_id: "91000000-0000-4000-8000-000000000003",
      message_type: "controller.revoked",
      controller_epoch: epoch,
      reason: "debate_terminal",
    });
    socket.emit(
      "message",
      envelope("replay.completed", 4, {
        scope: "all",
        turn_id: firstTurnId,
        control_version: 2,
      }),
    );
    await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(2));
    await waitFor(() => {
      const acquires = socket
        .commands()
        .filter(
          (command) => command.command_type === "playback.controller.acquire",
        );
      expect(acquires).toHaveLength(2);
    });
    expect(socket.closed).not.toHaveBeenCalled();
  });

  it("renders early Finish as finished while playback remains terminal", async () => {
    const initial = detail(
      "running",
      {
        status: "waiting_next",
        mode: "live",
        current_turn_id: firstTurnId,
        control_version: 4,
        next_turn_ready: false,
      },
      [turns()[0]!],
    );
    const socket = new TestSocket();
    render(
      <DebateStage
        api={apiFor(initial, initial.playback)}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit("message", acquired(4));
    socket.emit(
      "message",
      envelope("debate.stopped", 1, {
        final_states: { debate: "debate_finished" },
        downstream_outcome: "stopped",
        safe_error_code: "debate_finished_partial",
      }),
    );

    await waitFor(() =>
      expect(
        document.querySelector('[data-classroom-phase="finished"]'),
      ).toBeTruthy(),
    );
    expect(screen.getAllByText(speech("First")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Debate complete")).toBeNull();
    expect(screen.queryByText("Debate stopped")).toBeNull();
  });

  it("restores the complete transcript only after final replay completion", async () => {
    const prefix = [turns()[0]!];
    const initial = detail(
      "completed",
      {
        status: "playing",
        mode: "replay",
        current_turn_id: secondTurnId,
        control_version: 8,
      },
      prefix,
    );
    const final = detail("completed", {
      status: "completed",
      mode: "live",
      current_turn_id: null,
      control_version: 9,
    });
    const refreshSnapshot = vi.fn().mockResolvedValue(final);
    const socket = new TestSocket();
    render(
      <DebateStage
        api={apiFor(initial, initial.playback)}
        debateId={debateId}
        detail={initial}
        currentAudioDebateId={debateId}
        refreshSnapshot={refreshSnapshot}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit("message", acquired(8));
    socket.emit(
      "message",
      envelope("replay.completed", 1, {
        scope: "all",
        turn_id: secondTurnId,
        control_version: 9,
      }),
    );
    await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByText(speech("Second"))).toBeTruthy(),
    );
    expect(screen.getByText("Debate complete")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Replay whole debate" }),
    ).toBeTruthy();
  });
});
