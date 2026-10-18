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
import { BetaDebateStage } from "../components/debate-beta/stage";
import type { DebateDetail, DebatePlaybackState } from "../lib/api";

// First entry into a running Debate, then Next. Production runs two backend
// replicas; the live event fan-out and media tickets are per process. With no
// or a stale load-balancer cookie (e.g. right after a redeploy) the page's
// parallel requests can be pinned to different replicas, so the socket misses
// the events that Start/Next commit elsewhere and then sees a sequence gap
// (or the server closes the stream on its own gap check). The stage used to
// park on "disconnected" with no speech until the teacher went Back and
// re-entered; it now does that re-entry itself.

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
        : type === "close" && typeof value === "number"
          ? new CloseEvent(type, { code: value })
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

function firstEntry() {
  // Already running: the first turn was spoken, the second is ready.
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
  initial.last_sequence = 1;
  const advanced: DebatePlaybackState = {
    ...initial.playback,
    status: "ready",
    current_turn_id: secondTurnId,
    control_version: 3,
    next_turn_ready: false,
  };
  // What the replica that served Next committed (sequences 2-4).
  const fresh = detail("running", {
    status: "waiting_next",
    current_turn_id: secondTurnId,
    control_version: 4,
    next_turn_ready: true,
  });
  fresh.last_sequence = 4;
  const first = new TestSocket();
  const second = new TestSocket();
  const socketFactory = vi
    .fn()
    .mockReturnValueOnce(first)
    .mockReturnValueOnce(second);
  const api = apiFor(initial, advanced);
  const refreshSnapshot = vi.fn().mockResolvedValue(fresh);
  const view = render(
    <BetaDebateStage
      api={api}
      debateId={debateId}
      detail={initial}
      refreshSnapshot={refreshSnapshot}
      socketFactory={socketFactory}
    />,
  );
  return { api, first, second, socketFactory, refreshSnapshot, view };
}

async function enterAndPressNext(first: TestSocket) {
  await waitFor(() => expect(first.hasListeners("open")).toBe(true));
  act(() => {
    first.emit("open");
    first.emit("message", acquired(2));
  });
  const next = screen.getByRole("button", { name: "Next" });
  await waitFor(() => expect((next as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(next);
}

describe("beta stage first entry then Next", () => {
  it.each([
    [
      "the socket sees a sequence gap",
      (socket: TestSocket) =>
        socket.emit(
          "message",
          envelope("playback.waiting_next", 4, {
            mode: "live",
            completed_turn_id: secondTurnId,
            control_version: 4,
            next_turn_ready: true,
          }),
        ),
    ],
    [
      "the server closes the stream",
      (socket: TestSocket) => socket.emit("close", 1011),
    ],
  ])(
    "shows the next speech without Back and re-entry when %s",
    async (_case, breakStream) => {
      const { api, first, second, socketFactory, refreshSnapshot, view } =
        firstEntry();
      await enterAndPressNext(first);
      await waitFor(() =>
        expect(api.advanceDebatePlayback).toHaveBeenCalledTimes(1),
      );
      // Next's own events were committed on the other replica and never
      // reach this socket; the next one it does carry is out of order.
      act(() => breakStream(first));
      await waitFor(() => expect(socketFactory).toHaveBeenCalledTimes(2), {
        timeout: 3000,
      });
      expect(refreshSnapshot).toHaveBeenCalled();
      await waitFor(() => expect(second.hasListeners("open")).toBe(true));
      act(() => {
        second.emit("open");
        second.emit("message", acquired(4));
      });
      await waitFor(() =>
        expect(screen.getAllByText(speech("Second")).length).toBeGreaterThan(0),
      );
      const stage = view.container.querySelector("section[data-connection]");
      expect(stage?.getAttribute("data-connection")).toBe("connected");
      expect(
        second
          .commands()
          .some((c) => c.command_type === "playback.controller.acquire"),
      ).toBe(true);
      const next = screen.getByRole("button", { name: "Next" });
      await waitFor(() =>
        expect((next as HTMLButtonElement).disabled).toBe(false),
      );
      // Recovery re-reads state; it never repeats the Next mutation.
      expect(api.advanceDebatePlayback).toHaveBeenCalledTimes(1);
    },
  );

  it("does not re-enter on its own after a sign-in or origin rejection", async () => {
    const { first, socketFactory } = firstEntry();
    await enterAndPressNext(first);
    act(() => first.emit("close", 4401));
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(socketFactory).toHaveBeenCalledTimes(1);
  });
});
