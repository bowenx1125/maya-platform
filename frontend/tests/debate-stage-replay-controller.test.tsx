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
    status: "completed",
    created_at: "2026-09-07T00:00:00Z",
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
});
