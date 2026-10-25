import {
  act,
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
import { BetaDebateStage } from "../components/debate-beta/stage";
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

vi.mock("../components/stage3d/scholar-scene", () => ({
  ScholarScene: ({ overlay }: { overlay?: import("react").ReactNode }) => (
    <div>{overlay}</div>
  ),
}));
vi.mock("../components/debate-beta/stage/bubble-progress", () => ({
  bubbleLineFrom: (speech: string) => speech,
  bubbleProgressFrom: (speech: string) => speech,
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
      segment_turn: null,
      audio_ready: false,
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
      segment_turn: null,
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
    background: "",
    topic: "Should the United States ban TikTok's recommendation algorithm?",
    status,
    created_at: "2026-08-28T00:00:00Z",
    audio_restore_needed: false,
    prepared_turns: 0,
    expected_turns: 0,
    preview: null,
    output_language: "en",
    turn_protocol: null,
    preview_turns: [],
    final_input_frozen: false,
    stall: null,
    revision: 1,
    last_sequence: 0,
    rule_set_id: "ordered_multi_expert_mutual_learning_v1",
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
        agent_name: "Kaikai",
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
    freezeFinalInput: vi.fn(),
    listProviderDataCallManifests: vi.fn().mockResolvedValue({
      scope_id: initial.id,
      items: [],
    }),
    retryDebatePreparation: vi.fn().mockResolvedValue(replay),
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

vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe.each([
  ["classic", DebateStage],
  ["beta", BetaDebateStage],
] as const)("%s text-only publication", (_name, Stage) => {
  it.each(["preparing", "waiting_next"] as const)(
    "recovers unpublished text from %s without an audio handshake",
    async (status) => {
      const initial = detail(
        "running",
        {
          status,
          current_turn_id: status === "preparing" ? secondTurnId : firstTurnId,
          control_version: 2,
          next_turn_ready: false,
        },
        turns().slice(0, 1),
      );
      const fresh = detail("running", {
        status: "waiting_next",
        current_turn_id: secondTurnId,
        control_version: 3,
        next_turn_ready: true,
      });
      fresh.last_sequence = 1;
      const socket = new TestSocket();
      const api = apiFor(initial, fresh.playback);
      const refreshSnapshot = vi.fn().mockResolvedValue(fresh);
      render(
        <Stage
          api={api}
          debateId={debateId}
          detail={initial}
          refreshSnapshot={refreshSnapshot}
          socketFactory={() => socket}
        />,
      );
      await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
      act(() => {
        socket.emit("open");
        socket.emit("message", acquired(2));
        socket.emit(
          "message",
          envelope("playback.waiting_next", 1, {
            mode: "live",
            completed_turn_id: secondTurnId,
            control_version: 3,
            next_turn_ready: true,
          }),
        );
      });
      await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1));
      await waitFor(() =>
        expect(screen.getAllByText(speech("Second")).length).toBeGreaterThan(0),
      );
      expect(
        socket
          .commands()
          .filter((c) => c.command_type === "playback.media.prepare"),
      ).toHaveLength(0);
      expect(api.advanceDebatePlayback).not.toHaveBeenCalled();
      expect(api.retryDebatePreparation).not.toHaveBeenCalled();
    },
  );

  it("loads newly published Next text when its websocket event is delayed", async () => {
    const initial = detail(
      "running",
      {
        status: "waiting_next",
        current_turn_id: firstTurnId,
        control_version: 2,
        next_turn_ready: true,
      },
      turns().slice(0, 1),
    );
    const fresh = detail("running", {
      status: "waiting_next",
      current_turn_id: secondTurnId,
      control_version: 3,
      next_turn_ready: false,
    });
    fresh.last_sequence = 1;
    const api = apiFor(initial, fresh.playback);
    const socket = new TestSocket();
    const refreshSnapshot = vi.fn().mockResolvedValue(fresh);
    render(
      <Stage
        api={api}
        debateId={debateId}
        detail={initial}
        refreshSnapshot={refreshSnapshot}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    act(() => {
      socket.emit("open");
      socket.emit("message", acquired(2));
    });
    const next = screen.getByRole("button", { name: "Next" });
    await waitFor(() =>
      expect((next as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(next);
    await waitFor(() =>
      expect(api.advanceDebatePlayback).toHaveBeenCalledTimes(1),
    );
    await waitFor(() =>
      expect(screen.getAllByText(speech("Second")).length).toBeGreaterThan(0),
    );
    expect(refreshSnapshot).toHaveBeenCalledTimes(1);
    expect(
      socket
        .commands()
        .filter((c) => c.command_type === "playback.media.prepare"),
    ).toHaveLength(0);
  });

  it("recovers the first published text after Start without revealing preview text", async () => {
    const initial = detail(
      "running",
      {
        status: "preparing",
        current_turn_id: firstTurnId,
        control_version: 1,
      },
      [],
    );
    const fresh = detail(
      "running",
      {
        status: "waiting_next",
        current_turn_id: firstTurnId,
        control_version: 2,
        next_turn_ready: true,
      },
      turns().slice(0, 1),
    );
    fresh.last_sequence = 1;
    const socket = new TestSocket();
    const api = apiFor(initial, fresh.playback);
    const refreshSnapshot = vi.fn().mockResolvedValue(fresh);
    render(
      <Stage
        api={api}
        debateId={debateId}
        detail={initial}
        refreshSnapshot={refreshSnapshot}
        socketFactory={() => socket}
      />,
    );
    expect(screen.queryByText(speech("First"))).toBeNull();
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    act(() => {
      socket.emit("open");
      socket.emit(
        "message",
        envelope("playback.waiting_next", 1, {
          mode: "live",
          completed_turn_id: firstTurnId,
          control_version: 2,
          next_turn_ready: true,
        }),
      );
    });
    await waitFor(() =>
      expect(screen.getAllByText(speech("First")).length).toBeGreaterThan(0),
    );
    expect(screen.queryByText(speech("Second"))).toBeNull();
    expect(
      socket
        .commands()
        .filter((c) => c.command_type === "playback.media.prepare"),
    ).toHaveLength(0);
    expect(api.retryDebatePreparation).not.toHaveBeenCalled();
  });
  it("ignores a stale waiting event instead of exposing unseen text", async () => {
    const initial = detail(
      "running",
      {
        status: "waiting_next",
        current_turn_id: firstTurnId,
        control_version: 4,
        next_turn_ready: true,
      },
      turns().slice(0, 1),
    );
    const socket = new TestSocket();
    const refreshSnapshot = vi.fn();
    render(
      <Stage
        api={apiFor(initial, initial.playback)}
        debateId={debateId}
        detail={initial}
        refreshSnapshot={refreshSnapshot}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    act(() => {
      socket.emit("open");
      socket.emit(
        "message",
        envelope("playback.waiting_next", 1, {
          mode: "live",
          completed_turn_id: secondTurnId,
          control_version: 3,
          next_turn_ready: true,
        }),
      );
    });
    expect(refreshSnapshot).not.toHaveBeenCalled();
    expect(screen.queryByText(speech("Second"))).toBeNull();
  });
});

describe.each([
  ["classic", DebateStage],
  ["beta", BetaDebateStage],
] as const)("%s next_not_ready visibility", (_name, Stage) => {
  it("surfaces next_not_ready instead of silently spinning", async () => {
    const initial = detail(
      "running",
      {
        status: "waiting_next",
        current_turn_id: firstTurnId,
        control_version: 2,
        next_turn_ready: true,
      },
      turns().slice(0, 1),
    );
    const api = apiFor(initial, initial.playback);
    const err = Object.assign(new Error("not ready"), {
      code: "next_not_ready",
      status: 409,
    });
    (api.advanceDebatePlayback as ReturnType<typeof vi.fn>).mockRejectedValue(
      err,
    );
    const refreshSnapshot = vi.fn().mockResolvedValue(initial);
    const socket = new TestSocket();
    render(
      <Stage
        api={api}
        debateId={debateId}
        detail={initial}
        refreshSnapshot={refreshSnapshot}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    act(() => {
      socket.emit("open");
      socket.emit("message", acquired(2));
    });
    const next = await screen.findByRole("button", { name: "Next" });
    await waitFor(() =>
      expect((next as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(next);
    await waitFor(() =>
      expect(api.advanceDebatePlayback).toHaveBeenCalledTimes(1),
    );
    await waitFor(() =>
      expect(screen.getByText(/Next turn is not ready yet/i)).toBeTruthy(),
    );
    // Still Turn 1 identity: do not pretend the advance succeeded.
    expect(screen.queryByText(speech("Second"))).toBeNull();
  });

  it("surfaces Next 503 host_load_pressure as visible controlError", async () => {
    const initial = detail(
      "running",
      {
        status: "waiting_next",
        current_turn_id: firstTurnId,
        control_version: 2,
        next_turn_ready: true,
      },
      turns().slice(0, 1),
    );
    const api = apiFor(initial, initial.playback);
    const err = Object.assign(new Error("Server is busy. Please try again."), {
      code: "host_load_pressure",
      status: 503,
    });
    (api.advanceDebatePlayback as ReturnType<typeof vi.fn>).mockRejectedValue(
      err,
    );
    const refreshSnapshot = vi.fn().mockResolvedValue(initial);
    const socket = new TestSocket();
    render(
      <Stage
        api={api}
        debateId={debateId}
        detail={initial}
        refreshSnapshot={refreshSnapshot}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    act(() => {
      socket.emit("open");
      socket.emit("message", acquired(2));
    });
    const next = await screen.findByRole("button", { name: "Next" });
    await waitFor(() =>
      expect((next as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(next);
    await waitFor(() =>
      expect(api.advanceDebatePlayback).toHaveBeenCalledTimes(1),
    );
    await waitFor(() =>
      expect(
        screen.getByText(/Server is busy\. Please try again\./i),
      ).toBeTruthy(),
    );
    // Must not silently clear the failure or fake-advance.
    expect(screen.queryByText(speech("Second"))).toBeNull();
  });
});
