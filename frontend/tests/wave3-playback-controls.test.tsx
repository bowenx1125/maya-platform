import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AvatarConfig } from "../components/avatar";
import { DebateStage, type PlaybackSocket } from "../components/debate/stage";
import type { DebateDetail, DebatePlaybackState } from "../lib/api";

vi.mock("../components/avatar/avatar-preview", () => ({
  AvatarPreview: ({ fallbackLabel }: { fallbackLabel?: string }) => (
    <div>{fallbackLabel ?? "avatar"}</div>
  ),
}));

const debateId = "20000000-0000-4000-8000-000000000001";
const participantA = "30000000-0000-4000-8000-000000000001";
const participantB = "30000000-0000-4000-8000-000000000002";
const turnA = "40000000-0000-4000-8000-000000000001";
const turnB = "40000000-0000-4000-8000-000000000002";
const epoch = "50000000-0000-4000-8000-000000000001";
const avatar: AvatarConfig = {
  template_id: "wave1-default-head",
  material_theme: "demo",
  eye_color: null,
  default_expression: "neutral",
  expression_strength: "medium",
  motion_style: "calm",
};

function turn(
  id: string,
  participant_id: string,
  turn_index: number,
  speech: string,
) {
  return {
    id,
    participant_id,
    round_no: 1,
    turn_index,
    speech,
    retrieval_status: "matched" as const,
    grounding_mode: "mixed" as const,
    sources: [{ source_filename: `${id}.md` }],
  };
}

function detail(
  status: DebateDetail["status"],
  playback: Partial<DebatePlaybackState> = {},
  public_turns = [turn(turnA, participantA, 0, "Alpha speech")],
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
    participants: [
      {
        id: participantA,
        slot: "A",
        order_index: 0,
        agent_id: "60000000-0000-4000-8000-000000000001",
        agent_name: "Bowen",
        agent_version_id: "70000000-0000-4000-8000-000000000001",
        version_label: "V1.0",
        knowledge_snapshot_id: "80000000-0000-4000-8000-000000000001",
        avatar_config: avatar,
        effective_voice_profile_id: null,
        voice_fallback_active: true,
        stance_mode: "assigned",
        initial_stance: "support",
        current_stance: "support",
      },
      {
        id: participantB,
        slot: "B",
        order_index: 1,
        agent_id: "60000000-0000-4000-8000-000000000002",
        agent_name: "KaiKai",
        agent_version_id: "70000000-0000-4000-8000-000000000002",
        version_label: "V1.0",
        knowledge_snapshot_id: "80000000-0000-4000-8000-000000000002",
        avatar_config: avatar,
        effective_voice_profile_id: null,
        voice_fallback_active: true,
        stance_mode: "assigned",
        initial_stance: "oppose",
        current_stance: "oppose",
      },
    ],
    public_turns,
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

class Socket implements PlaybackSocket {
  readonly sent: string[] = [];
  private listeners = new Map<string, Set<(event: Event) => void>>();
  send(data: string) {
    this.sent.push(data);
  }
  close = vi.fn();
  addEventListener(type: string, listener: (event: Event) => void) {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener);
    this.listeners.set(type, set);
  }
  removeEventListener(type: string, listener: (event: Event) => void) {
    this.listeners.get(type)?.delete(listener);
  }
  emit(type: string, data?: unknown) {
    const event =
      type === "message"
        ? new MessageEvent(type, { data: JSON.stringify(data) })
        : new Event(type);
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }
}

function acquired(control_version: number) {
  return {
    message_id: "91000000-0000-4000-8000-000000000001",
    message_type: "controller.acquired",
    result_version: 1,
    debate_id: debateId,
    occurred_at: "2026-08-28T00:00:00Z",
    command_id: "92000000-0000-4000-8000-000000000001",
    controller_epoch: epoch,
    control_version,
  };
}

function envelope(
  event_type: string,
  sequence: number,
  payload: Record<string, unknown>,
) {
  return {
    event_id: `90000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
    event_type,
    event_version: 1,
    debate_id: debateId,
    sequence,
    occurred_at: "2026-08-28T00:00:00Z",
    payload,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Wave 3 playback controls", () => {
  it("does not reconnect automatically and exposes one manual retry", async () => {
    const initial = detail("running", {
      status: "playing",
      current_turn_id: turnA,
    });
    const first = new Socket();
    const second = new Socket();
    const refresh = vi.fn().mockResolvedValue(initial);
    const factory = vi
      .fn()
      .mockReturnValueOnce(first)
      .mockReturnValueOnce(second);
    render(
      <DebateStage
        api={{
          startDebate: vi.fn(),
          advanceDebatePlayback: vi.fn(),
          replayDebate: vi.fn(),
          pauseDebate: vi.fn(),
          resumeDebate: vi.fn(),
        }}
        debateId={debateId}
        detail={initial}
        refreshSnapshot={refresh}
        socketFactory={factory}
      />,
    );
    await waitFor(() => expect(first).toBeTruthy());
    first.emit("open");
    first.emit("close");
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(factory).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /Reconnect/ }));
    await waitFor(() => expect(factory).toHaveBeenCalledTimes(2));
    expect(refresh).toHaveBeenCalledTimes(1);
    second.emit("open");
  });

  it("restores replay speech and sources from the retained catalog", async () => {
    const initial = detail(
      "debate_finished",
      {
        status: "completed",
        mode: "live",
      },
      [
        turn(turnA, participantA, 0, "Alpha speech"),
        turn(turnB, participantB, 1, "Beta speech"),
      ],
    );
    const replayState = {
      ...initial.playback,
      status: "ready" as const,
      mode: "replay" as const,
      current_turn_id: turnA,
      control_version: 1,
    };
    const socket = new Socket();
    const api = {
      startDebate: vi.fn(),
      advanceDebatePlayback: vi.fn(),
      replayDebate: vi.fn().mockResolvedValue(replayState),
      pauseDebate: vi.fn(),
      resumeDebate: vi.fn(),
    };
    render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        currentAudioDebateId={debateId}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket).toBeTruthy());
    socket.emit("open");
    socket.emit("message", acquired(0));
    const replay = screen.getByRole("button", { name: /Replay whole debate/ });
    await waitFor(() => expect(replay).toHaveProperty("disabled", false));
    fireEvent.click(replay);
    await waitFor(() => expect(api.replayDebate).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        document.querySelector(
          '[data-playback-status="ready"][data-playback-mode="replay"]',
        ),
      ).toBeTruthy(),
    );
    socket.emit(
      "message",
      envelope("replay.started", 1, {
        scope: "all",
        turn_id: turnA,
        control_version: 1,
      }),
    );
    await waitFor(() =>
      expect(document.querySelector('[data-last-sequence="1"]')).toBeTruthy(),
    );
    await waitFor(() =>
      expect(screen.getAllByText("Alpha speech").length).toBeGreaterThan(0),
    );
    expect(screen.getAllByText(`${turnA}.md`).length).toBeGreaterThan(0);
  });

  it("uses Pause/Continue controls without changing Debate status", async () => {
    const initial = detail("running", {
      status: "playing",
      current_turn_id: turnA,
      control_version: 2,
    });
    const socket = new Socket();
    const paused = {
      ...initial.playback,
      status: "paused" as const,
      control_version: 3,
    };
    const resumed = {
      ...initial.playback,
      status: "ready" as const,
      control_version: 4,
    };
    const api = {
      startDebate: vi.fn(),
      advanceDebatePlayback: vi.fn(),
      replayDebate: vi.fn(),
      pauseDebate: vi.fn().mockResolvedValue(paused),
      resumeDebate: vi.fn().mockResolvedValue(resumed),
    };
    render(
      <DebateStage
        api={api}
        debateId={debateId}
        detail={initial}
        socketFactory={() => socket}
      />,
    );
    await waitFor(() => expect(socket).toBeTruthy());
    socket.emit("open");
    socket.emit("message", acquired(2));
    const pause = screen.getByRole("button", { name: /Pause/ });
    await waitFor(() => expect(pause).toHaveProperty("disabled", false));
    fireEvent.click(pause);
    await waitFor(() =>
      expect(api.pauseDebate).toHaveBeenCalledWith(
        debateId,
        { expected_control_version: 2 },
        expect.any(Object),
      ),
    );
    const cont = await screen.findByRole("button", { name: /Continue/ });
    expect(cont).toHaveProperty("disabled", false);
    fireEvent.click(cont);
    await waitFor(() => expect(api.resumeDebate).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        document.querySelector('[data-playback-status="ready"]'),
      ).toBeTruthy(),
    );
    socket.emit(
      "message",
      envelope("playback.resumed", 1, {
        turn_id: turnA,
        cursor_ms: 0,
        control_version: 4,
        playback_rate: 1,
      }),
    );
    await waitFor(() =>
      expect(
        document.querySelector('[data-playback-status="playing"]'),
      ).toBeTruthy(),
    );
    expect(screen.getByRole("button", { name: /Pause/ })).toBeTruthy();
  });
});
