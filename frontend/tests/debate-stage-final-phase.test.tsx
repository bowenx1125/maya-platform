import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DebatePlaybackApi,
  PlaybackSocket,
} from "../components/debate/stage";
import { BetaDebateStage } from "../components/debate-beta/stage";
import type { DebateDetail } from "../lib/api";

vi.mock("../components/avatar/avatar-preview", () => ({
  AvatarPreview: () => <div />,
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
const participantIds = [
  "30000000-0000-4000-8000-000000000001",
  "30000000-0000-4000-8000-000000000002",
];

function detail(publicCount = 8): DebateDetail {
  const publicTurns: DebateDetail["public_turns"] = Array.from(
    { length: publicCount },
    (_, index) => ({
      id: `40000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
      participant_id: participantIds[index % 2],
      turn_index: index,
      round_no: Math.floor(index / 2) + 1,
      speech: `Public speech ${index + 1}.`,
      retrieval_status: "matched",
      grounding_mode: "mixed",
      audio_ready: false,
      segment_turn: null,
      sources: [],
    }),
  );
  return {
    id: debateId,
    course_id: "10000000-0000-4000-8000-000000000001",
    background: "",
    topic: "A complete text classroom",
    status: "running",
    created_at: "2026-10-12T00:00:00Z",
    audio_restore_needed: false,
    prepared_turns: 6,
    expected_turns: 6,
    preview: null,
    output_language: "en",
    turn_protocol: null,
    teaching_protocol: "four_round_v1",
    preview_turns: [],
    final_input_frozen: true,
    stall: null,
    revision: 1,
    last_sequence: 8,
    rule_set_id: "ordered_multi_expert_mutual_learning_v1",
    round_count: 4,
    participants: participantIds.map((id, index) => ({
      id,
      slot: index === 0 ? "A" : "B",
      order_index: index,
      agent_id: `60000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
      agent_name: index === 0 ? "Laozi" : "Plato",
      agent_version_id: `70000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
      version_label: "V1.0",
      knowledge_snapshot_id: `80000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
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
    })),
    public_turns: publicTurns,
    playback: {
      status: "waiting_next",
      mode: "live",
      current_turn_id: publicTurns[publicCount - 1].id,
      cursor_ms: 0,
      control_version: 8,
      next_turn_ready: false,
    },
    interaction_status: "closed",
    insight_status: "not_started",
    report_status: "not_started",
  };
}

function api(): DebatePlaybackApi {
  return {
    startDebate: vi.fn(),
    advanceDebatePlayback: vi.fn(),
    pauseDebate: vi.fn(),
    resumeDebate: vi.fn(),
    freezeFinalInput: vi.fn(),
    retryDebatePreparation: vi.fn(),
    replayDebate: vi.fn(),
    listProviderDataCallManifests: vi.fn().mockResolvedValue({
      scope_id: debateId,
      items: [],
    }),
  };
}

class TestSocket implements PlaybackSocket {
  send = vi.fn();
  close = vi.fn();
  private readonly listeners = new Map<string, Set<(event: Event) => void>>();

  addEventListener(type: string, listener: (event: Event) => void): void {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: (event: Event) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  hasListeners(): boolean {
    return (this.listeners.get("open")?.size ?? 0) > 0;
  }

  emit(type: "open" | "message", value?: unknown): void {
    const event =
      type === "message"
        ? new MessageEvent(type, { data: JSON.stringify(value) })
        : new Event(type);
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }
}

function privateMessage(messageType: string, fields: Record<string, unknown>) {
  return {
    message_id: "91000000-0000-4000-8000-000000000001",
    message_type: messageType,
    result_version: 1,
    debate_id: debateId,
    occurred_at: "2026-10-12T00:00:00Z",
    command_id: "92000000-0000-4000-8000-000000000001",
    ...fields,
  };
}

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe.each([
  ["beta", BetaDebateStage],
] as const)("%s final text phase", (name, Stage) => {
  function renderStage(
    snapshot: DebateDetail,
    options?: {
      client: DebatePlaybackApi;
      socket: TestSocket;
      refreshSnapshot: () => Promise<DebateDetail>;
    },
  ) {
    render(
      <Stage
        api={options?.client ?? api()}
        debateId={debateId}
        detail={snapshot}
        labels={{
          stageTitle: "Acceptance stage",
          transcript: "Public Debate",
          phaseWaiting: "Waiting",
          phaseInProgress: "Generating",
          phaseFinished: "Completed",
        }}
        readOnly={!options}
        socketFactory={options ? () => options.socket : undefined}
        refreshSnapshot={options?.refreshSnapshot}
      />,
    );
    if (name === "beta") {
      fireEvent.click(screen.getByRole("button", { name: "Transcript" }));
    }
    return screen.getByRole("region", { name: "Acceptance stage" });
  }

  it("waits for End after the eighth public text without showing generation", () => {
    const stage = renderStage(detail());

    expect(stage.getAttribute("data-classroom-phase")).toBe("waiting");
    expect(
      screen.getByRole("heading", { name: "Public Debate Waiting" }),
    ).toBeTruthy();
    expect(screen.queryByText("Generating")).toBeNull();
  });

  it("keeps the completed label after End", () => {
    const snapshot = detail();
    snapshot.status = "debate_finished";
    snapshot.playback.status = "completed";
    const stage = renderStage(snapshot);

    expect(stage.getAttribute("data-classroom-phase")).toBe("finished");
    expect(
      screen.getByRole("heading", { name: "Public Debate Completed" }),
    ).toBeTruthy();
  });

  it("does not mark an actively playing final turn as waiting", () => {
    const snapshot = detail();
    snapshot.playback.status = "playing";
    const stage = renderStage(snapshot);

    expect(stage.getAttribute("data-classroom-phase")).toBe("in_progress");
  });

  it("preserves the next-turn preparation label before the final text", () => {
    const stage = renderStage(detail(7));

    expect(stage.getAttribute("data-classroom-phase")).toBe(
      name === "beta" ? "in_progress" : "waiting",
    );
  });

  it.each([
    "older-version",
    "older-sequence",
    "before-mutation",
    "controller-revoked",
    "unmounted",
    "two-stale-reads",
  ] as const)(
    "confirms Final after a concurrent %s recovery without a second mutation",
    async (snapshotRace) => {
      const initial = detail(6);
      initial.turn_protocol = "segments_v2";
      initial.final_input_frozen = false;
      const fresh = detail(6);
      fresh.turn_protocol = "segments_v2";
      fresh.last_sequence = 9;
      fresh.playback.control_version = 9;
      fresh.playback.next_turn_ready = true;
      let resolvePending!: (value: DebateDetail) => void;
      const pending = new Promise<DebateDetail>((resolve) => {
        resolvePending = resolve;
      });
      const refreshSnapshot = vi
        .fn()
        .mockReturnValueOnce(pending)
        .mockResolvedValue(
          snapshotRace === "two-stale-reads" ? initial : fresh,
        );
      const client = api();
      const socket = new TestSocket();
      renderStage(initial, { client, socket, refreshSnapshot });
      await waitFor(() => expect(socket.hasListeners()).toBe(true));
      act(() => {
        socket.emit("open");
        socket.emit(
          "message",
          privateMessage("controller.acquired", {
            controller_epoch: "50000000-0000-4000-8000-000000000001",
            control_version: 8,
          }),
        );
        socket.emit(
          "message",
          privateMessage("command.rejected", {
            code: "stale_control_version",
            recoverable: true,
            current_control_version: 8,
          }),
        );
      });
      await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1));
      fireEvent.click(screen.getByRole("button", { name: "Final" }));
      await waitFor(() =>
        expect(client.freezeFinalInput).toHaveBeenCalledTimes(1),
      );
      await act(async () => {
        if (
          snapshotRace === "older-version" ||
          snapshotRace === "older-sequence" ||
          snapshotRace === "two-stale-reads"
        ) {
          socket.emit("message", {
            event_id: "90000000-0000-4000-8000-000000000009",
            event_type: "playback.waiting_next",
            event_version: 1,
            debate_id: debateId,
            sequence: 9,
            occurred_at: "2026-10-12T00:00:00Z",
            payload: {
              mode: "live",
              completed_turn_id: initial.playback.current_turn_id,
              control_version: snapshotRace === "older-sequence" ? 8 : 9,
              next_turn_ready: true,
            },
          });
        } else if (snapshotRace === "controller-revoked") {
          socket.emit(
            "message",
            privateMessage("controller.revoked", {
              controller_epoch: "50000000-0000-4000-8000-000000000001",
              reason: "session_revoked",
            }),
          );
        } else if (snapshotRace === "unmounted") {
          cleanup();
        }
        resolvePending(initial);
        await pending;
      });
      if (
        snapshotRace === "controller-revoked" ||
        snapshotRace === "unmounted" ||
        snapshotRace === "two-stale-reads"
      ) {
        expect(client.freezeFinalInput).toHaveBeenCalledTimes(1);
        expect(client.advanceDebatePlayback).not.toHaveBeenCalled();
        expect(refreshSnapshot).toHaveBeenCalledTimes(
          snapshotRace === "two-stale-reads" ? 4 : 1,
        );
        expect(screen.queryByRole("button", { name: "Next" })).toBeNull();
        return;
      }
      await waitFor(() =>
        expect(
          (screen.getByRole("button", { name: "Next" }) as HTMLButtonElement)
            .disabled,
        ).toBe(false),
      );
      expect(screen.queryByRole("button", { name: "Final" })).toBeNull();
      expect(client.freezeFinalInput).toHaveBeenCalledTimes(1);
      expect(client.advanceDebatePlayback).not.toHaveBeenCalled();
      expect(refreshSnapshot).toHaveBeenCalledTimes(2);
    },
  );
});
