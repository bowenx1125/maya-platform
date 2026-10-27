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
