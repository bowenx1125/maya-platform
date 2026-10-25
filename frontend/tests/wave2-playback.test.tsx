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
import type { AvatarConfig } from "../components/avatar";
import type {
  DebatePlaybackApi,
  PlaybackSocket,
} from "../components/debate/stage";
import type { DebateDetail, DebatePlaybackState } from "../lib/api";
import { PlatformApiError } from "../lib/api";
import {
  DebateStage,
  consumeEventSequence,
  deriveAvatarStates,
  parsePlaybackEvent,
} from "../components/debate/stage";

vi.mock("../components/stage3d/scholar-scene", () => ({
  ScholarScene: () => <div data-testid="scholar-scene" />,
}));

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
const finalTurnId = "40000000-0000-4000-8000-000000000004";
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
    background: "",
    status: overrides.status ?? "running",
    created_at: "2026-08-27T00:00:00Z",
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
    last_sequence: overrides.last_sequence ?? 0,
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
    public_turns: overrides.public_turns ?? [],
    playback: {
      status: "preparing",
      mode: "live",
      current_turn_id: turnId,
      cursor_ms: 0,
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
        : type === "close"
          ? ({
              type,
              code:
                typeof value === "number"
                  ? value
                  : typeof value === "object" && value && "code" in value
                    ? Number(value.code)
                    : 0,
            } as unknown as Event)
          : new Event(type);
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }

  commands(): Record<string, unknown>[] {
    return this.sent.map((item) => JSON.parse(item) as Record<string, unknown>);
  }
}

function fakeApi(initial: DebateDetail): DebatePlaybackApi {
  return {
    startDebate: vi.fn().mockResolvedValue(initial),
    advanceDebatePlayback: vi.fn().mockResolvedValue({
      ...initial.playback,
      status: "ready",
      current_turn_id: nextTurnId,
      next_turn_ready: false,
      control_version: initial.playback.control_version + 1,
    }),
    replayDebate: vi.fn().mockResolvedValue({
      ...initial.playback,
      mode: "replay",
      status: "ready",
    }),
    pauseDebate: vi.fn().mockResolvedValue({
      ...initial.playback,
      status: "paused",
      control_version: initial.playback.control_version + 1,
    }),
    resumeDebate: vi.fn().mockResolvedValue({
      ...initial.playback,
      status: "ready",
      control_version: initial.playback.control_version + 1,
    }),
    freezeFinalInput: vi.fn(),
    listProviderDataCallManifests: vi.fn().mockResolvedValue({
      scope_id: initial.id,
      items: [],
    }),
    retryDebatePreparation: vi.fn().mockResolvedValue({
      ...initial.playback,
      status: "preparing",
      control_version: initial.playback.control_version + 1,
    }),
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

function finalLiveDetail(): DebateDetail {
  const turns = [
    [turnId, participantAId, 1, 0],
    [nextTurnId, participantBId, 1, 1],
    ["40000000-0000-4000-8000-000000000003", participantAId, 2, 2],
    [finalTurnId, participantBId, 2, 3],
  ].map(([id, participantId, roundNo, turnIndex]) => ({
    id: String(id),
    participant_id: String(participantId),
    round_no: Number(roundNo),
    turn_index: Number(turnIndex),
    speech: `Published speech ${Number(turnIndex) + 1}.`,
    retrieval_status: "matched" as const,
    grounding_mode: "mixed" as const,
    segment_turn: null,
    sources: [],
  }));
  const initial = detail({ public_turns: turns });
  initial.playback = {
    ...initial.playback,
    status: "playing",
    mode: "live",
    current_turn_id: finalTurnId,
  };
  return initial;
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

  it("keeps provider-gated preparation non-ready until exact confirmation and retry", async () => {
    const initial = detail();
    const socket = new TestSocket();
    const api = fakeApi(initial);
    const manifestHash = "a".repeat(64);
    api.listProviderDataCallManifests = vi
      .fn()
      .mockResolvedValueOnce({
        scope_id: debateId,
        items: [
          {
            manifest_hash: manifestHash,
            turn_id: turnId,
            confirmation_revision: 1,
            confirmed: false,
          },
        ],
      })
      .mockResolvedValue({
        scope_id: debateId,
        items: [
          {
            manifest_hash: manifestHash,
            turn_id: turnId,
            confirmation_revision: 1,
            confirmed: true,
          },
        ],
      });
    const { container } = render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );

    await waitFor(() => expect(socket.hasListeners("message")).toBe(true));
    await act(async () => {
      socket.emit("message", {
        ...envelope("error", 1, {
          code: "provider_confirmation_required",
          message: "Teacher confirmation is required.",
          recoverable: true,
        }),
      });
    });
    await waitFor(() =>
      expect(api.listProviderDataCallManifests).toHaveBeenCalledWith(debateId),
    );
    expect(
      container.querySelector('[data-playback-status="preparing"]'),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Review exact disclosure" })
        .getAttribute("href"),
    ).toBe(`/teacher/provider-disclosures/${manifestHash}`);
    expect(
      screen
        .getByRole("link", { name: "Review all turn approvals" })
        .getAttribute("href"),
    ).toBe(`/teacher/provider-approvals/debates/${debateId}`);
    expect(
      socket
        .commands()
        .some((command) => command.command_type === "playback.media.prepare"),
    ).toBe(false);

    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
    fireEvent.focus(window);
    await waitFor(() =>
      expect(api.listProviderDataCallManifests).toHaveBeenCalledTimes(2),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Retry this turn" }),
      ).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry this turn" }));
    await waitFor(() =>
      expect(api.retryDebatePreparation).toHaveBeenCalledWith(
        debateId,
        { expected_control_version: 0, turn_id: turnId },
        { idempotency: expect.anything() },
      ),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("provider-query-gate")).toBeNull(),
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
    const onCurrentAudioDebateIdChange = vi.fn();
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
        onCurrentAudioDebateIdChange={onCurrentAudioDebateIdChange}
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
      expect(onCurrentAudioDebateIdChange).toHaveBeenCalledWith(debateId),
    );
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
      screen.queryByText("Waiting for the teacher controller…"),
    ).toBeNull();
    expect(
      socket
        .commands()
        .filter((command) => command.command_type === "playback.media.prepare"),
    ).toHaveLength(0);
  });

  it.each([
    ["debate.failed", "failed", "Debate needs attention"],
    ["debate.stopped", "stopped", "Stopped"],
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

  it("waits for live teacher Next and prepares exactly the adjacent turn", async () => {
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
          segment_turn: null,
          sources: [],
        },
      ],
    });
    initial.playback = {
      ...initial.playback,
      status: "waiting_next",
      mode: "live",
      current_turn_id: turnId,
      control_version: 3,
      next_turn_ready: false,
    };
    const socket = new TestSocket();
    const api = fakeApi(initial);
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
    socket.emit("message", {
      message_id: "91000000-0000-0000-8000-000000000030",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-0000-8000-000000000030",
      controller_epoch: epoch,
      control_version: 3,
    });
    socket.emit(
      "message",
      envelope("playback.waiting_next", 1, {
        mode: "live",
        completed_turn_id: turnId,
        control_version: 3,
        next_turn_ready: false,
      }),
    );
    expect(screen.getAllByText("The first public speech.")).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: "Next" })).toHaveProperty(
      "disabled",
      true,
    );

    socket.emit(
      "message",
      envelope("playback.waiting_next", 2, {
        mode: "live",
        completed_turn_id: turnId,
        control_version: 3,
        next_turn_ready: true,
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Next" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
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

  it("hides connection chrome for an authoritative terminal revocation", async () => {
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
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000021",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      controller_epoch: epoch,
      control_version: 0,
    });
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000022",
      message_type: "controller.revoked",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      controller_epoch: epoch,
      reason: "debate_terminal",
    });

    await waitFor(() =>
      expect(
        container.querySelector('[data-connection-reason="terminal"]'),
      ).toBeTruthy(),
    );
    expect(container.querySelector("[data-state]")).toBeNull();
    expect(screen.queryByRole("button", { name: /Reconnect/ })).toBeNull();
    expect(screen.queryByText("unconnected")).toBeNull();
    socket.emit("message", envelope("debate.stopped", 1, {}));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(
      socket
        .commands()
        .filter(
          (command) => command.command_type === "playback.controller.acquire",
        ),
    ).toHaveLength(1);
  });

  it("acquires one Replay controller when completion precedes debate_terminal revocation", async () => {
    const initial = finalLiveDetail();
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
    await waitFor(() =>
      expect(
        socket
          .commands()
          .filter(
            (command) => command.command_type === "playback.controller.acquire",
          ),
      ).toHaveLength(1),
    );
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000025",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      controller_epoch: epoch,
      control_version: 0,
    });
    socket.emit(
      "message",
      envelope("playback.completed", 1, {
        turn_id: finalTurnId,
        control_version: 0,
      }),
    );
    await waitFor(() =>
      expect(
        container.querySelector('[data-playback-status="completed"]'),
      ).toBeTruthy(),
    );
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000026",
      message_type: "controller.revoked",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      controller_epoch: epoch,
      reason: "debate_terminal",
    });

    await waitFor(() =>
      expect(
        socket
          .commands()
          .filter(
            (command) => command.command_type === "playback.controller.acquire",
          ),
      ).toHaveLength(2),
    );
    expect(
      container.querySelector('[data-connection="connected"]'),
    ).toBeTruthy();
    expect(
      container.querySelector('[data-connection-reason="none"]'),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Reconnect/ })).toBeNull();
  });

  it("waits for authoritative completion when debate_terminal revocation wins the race", async () => {
    const initial = finalLiveDetail();
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
    await waitFor(() =>
      expect(
        socket
          .commands()
          .filter(
            (command) => command.command_type === "playback.controller.acquire",
          ),
      ).toHaveLength(1),
    );
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000027",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      controller_epoch: epoch,
      control_version: 0,
    });
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000028",
      message_type: "controller.revoked",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      controller_epoch: epoch,
      reason: "debate_terminal",
    });

    await waitFor(() =>
      expect(
        container.querySelector('[data-connection-reason="terminal"]'),
      ).toBeTruthy(),
    );
    expect(
      socket
        .commands()
        .filter(
          (command) => command.command_type === "playback.controller.acquire",
        ),
    ).toHaveLength(1);

    socket.emit(
      "message",
      envelope("playback.completed", 1, {
        turn_id: finalTurnId,
        control_version: 0,
      }),
    );
    await waitFor(() =>
      expect(
        socket
          .commands()
          .filter(
            (command) => command.command_type === "playback.controller.acquire",
          ),
      ).toHaveLength(2),
    );
    expect(
      container.querySelector('[data-connection="connected"]'),
    ).toBeTruthy();
    expect(
      container.querySelector('[data-connection-reason="none"]'),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Reconnect/ })).toBeNull();
  });

  it("shows superseded without reconnecting or reacquiring control", async () => {
    const retainedSpeech = "This published speech and its source stay visible.";
    const initial = detail({
      public_turns: [
        {
          id: turnId,
          participant_id: participantAId,
          round_no: 1,
          turn_index: 0,
          speech: retainedSpeech,
          retrieval_status: "matched",
          grounding_mode: "mixed",
          segment_turn: null,
          sources: [{ source_filename: "retained-source.md" }],
        },
      ],
    });
    initial.playback = {
      ...initial.playback,
      status: "playing",
      current_turn_id: turnId,
    };
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
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000023",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      controller_epoch: epoch,
      control_version: 0,
    });
    await waitFor(() =>
      expect(
        socket
          .commands()
          .filter(
            (command) => command.command_type === "playback.controller.acquire",
          ),
      ).toHaveLength(1),
    );
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000024",
      message_type: "controller.revoked",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      controller_epoch: epoch,
      reason: "superseded",
    });
    socket.emit("message", {
      ...envelope("snapshot", 1, {
        ...snapshotPayload(initial.playback),
        latest_sequence: 1,
        public_turns: initial.public_turns,
      }),
    });

    expect(
      await screen.findAllByText(/Another teacher page has taken control/),
    ).not.toHaveLength(0);
    expect(screen.getAllByText(retainedSpeech)).not.toHaveLength(0);
    expect(screen.getByText("retained-source.md")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Reconnect/ })).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(
      socket
        .commands()
        .filter(
          (command) => command.command_type === "playback.controller.acquire",
        ),
    ).toHaveLength(1);
    expect(
      container.querySelector('[data-connection-reason="superseded"]'),
    ).toBeTruthy();
  });

  it("maps 4401 and 4403 exactly, lets close win after error, and offers no reconnect", async () => {
    const initial = detail({ status: "completed" });
    const firstSocket = new TestSocket();
    const { container } = render(
      <DebateStage
        api={fakeApi(initial)}
        debateId={debateId}
        detail={initial}
        socketFactory={() => firstSocket}
      />,
    );

    await waitFor(() => expect(firstSocket.hasListeners("open")).toBe(true));
    firstSocket.emit("error");
    firstSocket.emit("close", 4401);
    expect(
      await screen.findAllByText(
        /Your login has expired\. Please sign in again/,
      ),
    ).not.toHaveLength(0);
    expect(
      container.querySelector('[data-connection-reason="session_expired"]'),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Reconnect/ })).toBeNull();

    cleanup();
    const secondSocket = new TestSocket();
    const secondRender = render(
      <DebateStage
        api={fakeApi(initial)}
        debateId={debateId}
        detail={initial}
        socketFactory={() => secondSocket}
      />,
    );
    await waitFor(() => expect(secondSocket.hasListeners("open")).toBe(true));
    secondSocket.emit("error");
    secondSocket.emit("close", 4403);
    expect(
      await screen.findAllByText(/classroom address does not match/),
    ).not.toHaveLength(0);
    expect(
      secondRender.container.querySelector(
        '[data-connection-reason="origin_mismatch"]',
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Reconnect/ })).toBeNull();
  });

  it("does not auto acquire but replays on demand after a finished reload", async () => {
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
          segment_turn: null,
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
      next_turn_ready: false,
    };
    const socket = new TestSocket();
    const api = fakeApi(initial);
    api.replayDebate = vi.fn().mockResolvedValue(replayState);
    const { container } = render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        currentAudioDebateId={debateId}
        socketFactory={() => socket}
      />,
    );

    expect(container.querySelector("[data-state]")).toBeNull();
    expect(screen.queryByRole("button", { name: /Reconnect/ })).toBeNull();
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    await waitFor(() =>
      expect(
        socket
          .commands()
          .filter(
            (command) => command.command_type === "playback.controller.acquire",
          ),
      ).toHaveLength(0),
    );
    const replayButton = screen.getByRole("button", {
      name: "Replay whole debate",
    });
    expect((replayButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(replayButton);
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

    socket.emit("message", {
      message_id: "91000000-0000-0000-8000-000000000061",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-0000-8000-000000000061",
      controller_epoch: epoch,
      control_version: 0,
    });
    await waitFor(() =>
      expect(api.replayDebate).toHaveBeenCalledWith(debateId, 0),
    );
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
  });

  it.each([
    ["current", debateId, false],
    ["old", "10000000-0000-4000-8000-000000000099", true],
  ] as const)(
    "gates whole replay when the course audio pointer is %s",
    async (_pointerState, pointer, shouldDisable) => {
      const initial = detail({
        status: "debate_finished",
        public_turns: [
          {
            id: turnId,
            participant_id: participantAId,
            round_no: 1,
            turn_index: 0,
            speech: "A published speech whose audio may be retained.",
            retrieval_status: "matched",
            grounding_mode: "mixed",
            segment_turn: null,
            sources: [],
          },
        ],
      });
      initial.playback = {
        ...initial.playback,
        status: "completed",
        mode: "live",
        current_turn_id: null,
      };
      const socket = new TestSocket();
      const api = fakeApi(initial);
      render(
        <DebateStage
          api={api}
          debateId={debateId}
          detail={initial}
          currentAudioDebateId={pointer}
          socketFactory={() => socket}
        />,
      );

      await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
      socket.emit("open");
      socket.emit("message", {
        message_id: "91000000-0000-0000-8000-000000000062",
        message_type: "controller.acquired",
        result_version: 1,
        debate_id: debateId,
        occurred_at: "2026-08-27T00:00:00Z",
        command_id: "92000000-0000-0000-8000-000000000062",
        controller_epoch: epoch,
        control_version: 0,
      });

      const replayButton = screen.getByRole("button", {
        name: "Replay whole debate",
      });
      await waitFor(() =>
        expect((replayButton as HTMLButtonElement).disabled).toBe(
          shouldDisable,
        ),
      );
      if (shouldDisable) {
        expect(
          screen.getAllByText("This audio is no longer retained.").length,
        ).toBeGreaterThan(0);
        fireEvent.click(replayButton);
        expect(api.replayDebate).not.toHaveBeenCalled();
      } else {
        fireEvent.click(replayButton);
        await waitFor(() =>
          expect(api.replayDebate).toHaveBeenCalledWith(debateId, 0),
        );
      }
    },
  );

  it("updates the local retention pointer after start before terminal replay", async () => {
    const publicTurn = {
      id: turnId,
      participant_id: participantAId,
      round_no: 1,
      turn_index: 0,
      speech: "A published speech after start.",
      retrieval_status: "matched" as const,
      grounding_mode: "mixed" as const,
      segment_turn: null,
      sources: [],
    };
    const initial = detail({ status: "draft" });
    initial.playback = {
      ...initial.playback,
      status: "preparing",
      current_turn_id: turnId,
    };
    const started = {
      ...initial,
      status: "running" as const,
      public_turns: [publicTurn],
      playback: {
        ...initial.playback,
        status: "playing" as const,
        current_turn_id: turnId,
      },
    };
    const finished = {
      ...started,
      status: "debate_finished" as const,
      playback: {
        ...started.playback,
        status: "completed" as const,
        current_turn_id: null,
      },
    };
    const socket = new TestSocket();
    const api = fakeApi(initial);
    api.startDebate = vi.fn().mockResolvedValue(started);
    const onCurrentAudioDebateIdChange = vi.fn();
    const { rerender } = render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        currentAudioDebateId={null}
        onCurrentAudioDebateIdChange={onCurrentAudioDebateIdChange}
        socketFactory={() => socket}
      />,
    );

    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    fireEvent.click(screen.getByRole("button", { name: "Start debate" }));
    await waitFor(() =>
      expect(onCurrentAudioDebateIdChange).toHaveBeenCalledWith(debateId),
    );

    rerender(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={finished}
        currentAudioDebateId={null}
        onCurrentAudioDebateIdChange={onCurrentAudioDebateIdChange}
        socketFactory={() => socket}
      />,
    );
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
      message_id: "91000000-0000-4000-8000-000000000063",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000063",
      controller_epoch: epoch,
      control_version: 0,
    });
    await waitFor(() =>
      expect(
        (
          screen.getByRole("button", {
            name: "Replay whole debate",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false),
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Replay whole debate" }),
    );
    await waitFor(() => expect(api.replayDebate).toHaveBeenCalled());
  });

  it("treats ordered replay and debate terminal events as terminal", async () => {
    const firstSpeech = "A published speech";
    const secondSpeech = "The restored historical speech.";
    const initial = detail({
      status: "debate_finished",
      public_turns: [
        {
          id: turnId,
          participant_id: participantAId,
          round_no: 1,
          turn_index: 0,
          speech: firstSpeech,
          retrieval_status: "matched",
          grounding_mode: "mixed",
          segment_turn: null,
          sources: [],
        },
      ],
    });
    initial.playback = {
      ...initial.playback,
      mode: "replay",
      status: "playing",
      current_turn_id: turnId,
    };
    const final = {
      ...initial,
      status: "completed" as const,
      public_turns: [
        ...initial.public_turns,
        {
          id: nextTurnId,
          participant_id: participantBId,
          round_no: 1,
          turn_index: 1,
          speech: secondSpeech,
          retrieval_status: "matched" as const,
          grounding_mode: "mixed" as const,
          segment_turn: null,
          sources: [],
        },
      ],
      last_sequence: 2,
      playback: {
        ...initial.playback,
        mode: "live" as const,
        status: "completed" as const,
        current_turn_id: null,
        control_version: 3,
      },
    };
    const refreshSnapshot = vi.fn().mockResolvedValue(final);
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
    const replayCompleted = envelope("replay.completed", 1, {
      scope: "all",
      turn_id: turnId,
      control_version: 2,
    });
    const debateCompleted = envelope("debate.completed", 2, {
      final_states: {},
      downstream_outcome: "completed",
    });
    socket.emit("message", replayCompleted);
    socket.emit("message", debateCompleted);
    await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getAllByText(secondSpeech).length).toBeGreaterThan(0),
    );
    expect(
      document.querySelector('[data-connection="reconnecting"]'),
    ).toBeNull();
    expect(
      socket
        .commands()
        .filter((command) => command.command_type === "playback.media.prepare"),
    ).toHaveLength(0);
  });

  it("uses the authoritative snapshot to hold an intermediate full replay at the waiting gate after reconnect", async () => {
    const firstPublicTurn = {
      id: turnId,
      participant_id: participantAId,
      round_no: 1,
      turn_index: 0,
      speech: "The first public speech.",
      retrieval_status: "matched" as const,
      grounding_mode: "mixed" as const,
      segment_turn: null,
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
        status: "waiting_next" as const,
        mode: "replay" as const,
        current_turn_id: turnId,
        control_version: 2,
        next_turn_ready: true,
      },
    };
    const advanced = {
      playback: {
        ...intermediate.playback,
        status: "ready" as const,
        current_turn_id: nextTurnId,
        control_version: 3,
        next_turn_ready: false,
      },
    };
    const refreshSnapshot = vi.fn().mockResolvedValue(intermediate);
    const firstSocket = new TestSocket();
    const secondSocket = new TestSocket();
    const socketFactory = vi
      .fn()
      .mockReturnValueOnce(firstSocket)
      .mockReturnValueOnce(secondSocket);
    const api = fakeApi(initial);
    api.advanceDebatePlayback = vi.fn().mockResolvedValue(advanced.playback);
    render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        refreshSnapshot={refreshSnapshot}
        socketFactory={socketFactory}
      />,
    );

    await waitFor(() => expect(firstSocket.hasListeners("open")).toBe(true));
    firstSocket.emit("open");
    firstSocket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000040",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000040",
      controller_epoch: epoch,
      control_version: 1,
    });
    firstSocket.emit("close");
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(refreshSnapshot).not.toHaveBeenCalled();
    expect(socketFactory).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("unconnected")).not.toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: /Reconnect/ }));
    await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(secondSocket.hasListeners("open")).toBe(true));
    secondSocket.emit("open");
    await waitFor(() =>
      expect(
        secondSocket
          .commands()
          .filter(
            (command) => command.command_type === "playback.controller.acquire",
          ),
      ).toHaveLength(1),
    );
    secondSocket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000041",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      command_id: "92000000-0000-4000-8000-000000000041",
      controller_epoch: "50000000-0000-4000-8000-000000000002",
      control_version: 2,
    });
    expect(
      secondSocket
        .commands()
        .filter((command) => command.command_type === "playback.media.prepare"),
    ).toHaveLength(0);
    const nextButton = screen.getByRole("button", { name: "Next" });
    await waitFor(() => expect(nextButton).toHaveProperty("disabled", false));
    fireEvent.click(nextButton);
    await waitFor(() =>
      expect(api.advanceDebatePlayback).toHaveBeenCalledWith(debateId, {
        expected_control_version: 2,
        expected_current_turn_id: turnId,
      }),
    );
    await waitFor(() => {
      const prepareCommands = secondSocket
        .commands()
        .filter((command) => command.command_type === "playback.media.prepare");
      expect(prepareCommands).toHaveLength(1);
      expect(prepareCommands[0]?.turn_id).toBe(nextTurnId);
      expect(prepareCommands[0]?.playback_action).toBe("replay");
    });
    expect(
      secondSocket
        .commands()
        .filter((command) => command.command_type === "playback.media.prepare"),
    ).toHaveLength(1);
  });

  it("maps a manual reconnect HTTP 401 to session expired without opening another socket", async () => {
    const initial = detail();
    const socket = new TestSocket();
    const socketFactory = vi.fn(() => socket);
    const refreshSnapshot = vi
      .fn()
      .mockRejectedValue(
        new PlatformApiError(401, "Authentication is required."),
      );
    const authorities: Array<{
      connectionIssue: string | null;
      controllerReady: boolean;
    }> = [];
    const { container } = render(
      <DebateStage
        api={fakeApi(initial)}
        debateId={debateId}
        detail={initial}
        refreshSnapshot={refreshSnapshot}
        socketFactory={socketFactory}
        onAuthorityChange={(authority) => authorities.push(authority)}
      />,
    );

    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    socket.emit("message", {
      message_id: "91000000-0000-4000-8000-000000000042",
      message_type: "controller.acquired",
      result_version: 1,
      debate_id: debateId,
      occurred_at: "2026-08-27T00:00:00Z",
      controller_epoch: epoch,
      control_version: 0,
    });
    socket.emit("close");
    fireEvent.click(await screen.findByRole("button", { name: /Reconnect/ }));

    expect(
      await screen.findAllByText(
        /Your login has expired\. Please sign in again/,
      ),
    ).not.toHaveLength(0);
    expect(refreshSnapshot).toHaveBeenCalledTimes(1);
    expect(socketFactory).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /Reconnect/ })).toBeNull();
    expect(screen.queryByText("Authentication is required.")).toBeNull();
    expect(
      container.querySelector('[data-connection-reason="session_expired"]'),
    ).toBeTruthy();
    expect(authorities.at(-1)).toMatchObject({
      connectionIssue: "session_expired",
      controllerReady: false,
    });
  });

  it("does not misclassify a reconnect HTTP 403 as an origin mismatch", async () => {
    const initial = detail();
    const socket = new TestSocket();
    const refreshSnapshot = vi
      .fn()
      .mockRejectedValue(new PlatformApiError(403, "Access is forbidden."));
    const { container } = render(
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
    socket.emit("close");
    fireEvent.click(await screen.findByRole("button", { name: /Reconnect/ }));

    await screen.findByText("Access is forbidden.");
    expect(
      container.querySelector('[data-connection-reason="network"]'),
    ).toBeTruthy();
    expect(
      container.querySelector('[data-connection-reason="origin_mismatch"]'),
    ).toBeNull();
    expect(screen.queryByText(/classroom address does not match/)).toBeNull();
    expect(screen.getByRole("button", { name: /Reconnect/ })).toBeTruthy();
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

  it.each([DebateStage, BetaDebateStage])(
    "shows explicit text-only playback without attempting audio",
    async (Stage) => {
      const initial = detail();
      initial.playback.status = "ready";
      const socket = new TestSocket();
      const play = vi
        .spyOn(HTMLMediaElement.prototype, "play")
        .mockResolvedValue(undefined);
      const { container } = render(
        <Stage
          api={fakeApi(initial)}
          debateId={debateId}
          detail={initial}
          socketFactory={() => socket}
        />,
      );
      await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
      socket.emit("open");
      socket.emit("message", {
        message_id: "91000000-0000-4000-8000-000000000001",
        message_type: "controller.acquired",
        result_version: 1,
        debate_id: debateId,
        occurred_at: "2026-08-27T00:00:00Z",
        command_id: "92000000-0000-4000-8000-000000000001",
        controller_epoch: epoch,
        control_version: 0,
      });
      await waitFor(() =>
        expect(
          socket
            .commands()
            .some(
              (command) => command.command_type === "playback.media.prepare",
            ),
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
        text_only: true,
        media_url: null,
        expires_at: "2026-08-27T00:01:00Z",
      });
      socket.emit(
        "message",
        envelope("playback.started", 1, {
          turn_id: turnId,
          slot: "A",
          round_no: 1,
          speech: "Text-only classroom speech.",
          sources: [],
          playback_url: null,
          audio_ready: false,
          cursor_ms: 0,
          avatar_states: [],
        }),
      );
      socket.emit(
        "message",
        envelope("playback.completed", 2, {
          turn_id: turnId,
          cursor_ms: 0,
          control_version: 0,
        }),
      );
      socket.emit(
        "message",
        envelope("playback.waiting_next", 3, {
          mode: "live",
          completed_turn_id: turnId,
          control_version: 0,
          next_turn_ready: true,
        }),
      );
      await waitFor(() =>
        expect(
          container.querySelector('[data-playback-status="waiting_next"]'),
        ).toBeTruthy(),
      );
      expect(play).not.toHaveBeenCalled();
      expect(
        socket
          .commands()
          .some(
            (command) =>
              command.command_type === "playback.started_ack" ||
              command.command_type === "playback.ended_ack",
          ),
      ).toBe(false);
      expect(container.querySelector("audio")?.getAttribute("src")).toBeFalsy();
    },
  );

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

  it("holds a sequence gap until the teacher explicitly reconnects", async () => {
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
          segment_turn: null,
          sources: [],
        },
      ],
    });
    initial.playback = {
      ...initial.playback,
      status: "playing",
      current_turn_id: turnId,
    };
    const socket = new TestSocket();
    render(
      <DebateStage
        api={fakeApi(initial)}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket.hasListeners("open")).toBe(true));
    socket.emit("open");
    // Exactly these three actions and no strays. Order is not asserted:
    // replaying the whole session now sits with the speeches it replays
    // rather than in the row that drives a live lesson.
    expect(
      screen
        .getAllByRole("button")
        .map((button) => button.textContent)
        .sort(),
    ).toEqual(["Next", "Replay whole debate", "Start debate"]);
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
      document.querySelector('[data-connection="disconnected"]'),
    ).toBeTruthy();
    expect(
      screen.getAllByText(/Classroom state needs to be resynchronized/),
    ).not.toHaveLength(0);
    expect(screen.queryByText("unconnected")).toBeNull();
    expect(screen.getByRole("button", { name: /Reconnect/ })).toBeTruthy();
  });

  it.skip("sends ended acknowledgement only from the native audio ended event", async () => {
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
    await waitFor(() =>
      expect(
        container.querySelector('[data-playback-status="playing"]'),
      ).toBeTruthy(),
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
        mode: "live",
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
    expect(screen.getByRole("button", { name: "Next" })).toHaveProperty(
      "disabled",
      true,
    );
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
      name: "Next",
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
        mode: "live",
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
      segment_turn: null,
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

    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(refreshSnapshot).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Reconnect/ }));
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
      segment_turn: null,
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
      segment_turn: null,
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
      segment_turn: null,
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

describe("playback protocol helpers", () => {
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
        mode: "replay",
        completed_turn_id: turnId,
        control_version: 8,
        next_turn_ready: true,
      }),
    );
    expect(waiting?.event_type).toBe("playback.waiting_next");
  });
});
