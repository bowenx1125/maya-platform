import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "../components/locale";
import {
  DebateStage,
  type DebatePlaybackApi,
  type PlaybackSocket,
} from "../components/debate/stage";
import { BetaDebateStage } from "../components/debate-beta/stage";
import type { DebateDetail } from "../lib/api";

vi.mock("../components/avatar/avatar-preview", () => ({
  AvatarPreview: ({ fallbackLabel }: { fallbackLabel?: string }) => (
    <div>{fallbackLabel ?? "avatar"}</div>
  ),
}));

afterEach(() => cleanup());

const debateId = "20000000-0000-4000-8000-000000000001";
const courseId = "10000000-0000-4000-8000-000000000002";
const participantId = "30000000-0000-4000-8000-000000000001";
const turnId = "40000000-0000-4000-8000-000000000001";

class IdleSocket implements PlaybackSocket {
  send = vi.fn();
  close = vi.fn();
  addEventListener = vi.fn();
  removeEventListener = vi.fn();
}

const api: DebatePlaybackApi = {
  startDebate: vi.fn(),
  advanceDebatePlayback: vi.fn(),
  pauseDebate: vi.fn(),
  resumeDebate: vi.fn(),
  freezeFinalInput: vi.fn(),
  retryDebatePreparation: vi.fn(),
  listProviderDataCallManifests: vi.fn().mockResolvedValue({
    scope_id: debateId,
    items: [],
  }),
  replayDebate: vi.fn(),
};

function publicTurn(audioReady: boolean | null) {
  return {
    id: turnId,
    participant_id: participantId,
    round_no: 1,
    turn_index: 0,
    speech: "A source-grounded public speech.",
    retrieval_status: "matched" as const,
    grounding_mode: "rag_grounded" as const,
    audio_ready: audioReady,
    segment_turn: {
      schema_version: "segment_turn_v2" as const,
      segments: [
        {
          text: "A source-grounded paragraph.",
          source_ids: ["source-a"],
          reply_to: null,
        },
      ],
    },
    source_details: [
      {
        source_id: "source-a",
        source_filename: "synthetic-water-record.md",
        excerpt: "The record describes shared water maintenance.",
        query_text: "Find the shared water maintenance record.",
        version_label: "V2.0",
      },
    ],
    sources: [],
  } as unknown as DebateDetail["public_turns"][number];
}

function detail(audioReady: boolean | null): DebateDetail {
  return {
    id: debateId,
    course_id: courseId,
    topic: "Should a classroom compare source-grounded perspectives?",
    background: "",
    status: "completed",
    created_at: "2026-09-07T00:00:00Z",
    audio_restore_needed: false,
    prepared_turns: 1,
    expected_turns: 1,
    preview: null,
    output_language: "en",
    turn_protocol: "segments_v2",
    preview_turns: [],
    final_input_frozen: true,
    stall: null,
    revision: 1,
    last_sequence: 1,
    rule_set_id: "ordered_multi_agent_rounds_demo_v2",
    round_count: 2,
    participants: [
      {
        id: participantId,
        slot: "A",
        order_index: 0,
        agent_id: "60000000-0000-4000-8000-000000000001",
        agent_name: "River Keeper",
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
    public_turns: [publicTurn(audioReady)],
    playback: {
      status: "completed",
      mode: "live",
      current_turn_id: null,
      cursor_ms: 0,
      playback_rate: 1,
      control_version: 1,
      next_turn_ready: false,
    },
    interaction_status: "closed",
    insight_status: "not_started",
    report_status: "not_started",
  };
}

function renderClassic(audioReady: boolean | null, readOnly = true) {
  return render(
    <LocaleProvider initialLocale="en">
      <DebateStage
        api={api}
        debateId={debateId}
        detail={detail(audioReady)}
        readOnly={readOnly}
        socketFactory={() => new IdleSocket()}
      />
    </LocaleProvider>,
  );
}

describe("segments_v2 stage projection", () => {
  it("uses SegmentRagInspector for completed classic turns", () => {
    renderClassic(true);

    expect(screen.getAllByText("A source-grounded paragraph.")).toHaveLength(2);
    expect(screen.queryByTestId("evidence-trace-absent")).toBeNull();
    fireEvent.click(screen.getByText("Check RAG"));
    expect(screen.getByText("synthetic-water-record.md")).toBeTruthy();
    expect(
      screen.getByText("The record describes shared water maintenance."),
    ).toBeTruthy();
    expect(
      screen.getByText("Find the shared water maintenance record."),
    ).toBeTruthy();
    expect(screen.getAllByText("V2.0")).toHaveLength(2);
  });

  it("uses the same structured projection in the Beta stage", () => {
    render(
      <LocaleProvider initialLocale="en">
        <BetaDebateStage
          api={api}
          debateId={debateId}
          detail={detail(true)}
          readOnly
          socketFactory={() => new IdleSocket()}
        />
      </LocaleProvider>,
    );

    expect(screen.getByText("Check RAG")).toBeTruthy();
    expect(screen.queryByTestId("evidence-trace-absent")).toBeNull();
  });
});

describe("segments_v2 retained audio replay", () => {
  it.each([
    [true, false],
    [false, true],
    [null, true],
  ] as const)(
    "gates replay on every public turn audio_ready value (%s)",
    (audioReady, disabled) => {
      renderClassic(audioReady, false);
      const replay = screen.getByRole("button", {
        name: "Replay whole debate",
      });
      expect((replay as HTMLButtonElement).disabled).toBe(disabled);
    },
  );
});

it("shows current/total progress and connection color without separate connection or transcript counts", () => {
  const value = detail(true);
  value.round_count = 4;
  value.participants = Array.from({ length: 3 }, (_, index) => ({
    ...value.participants[0],
    id: index === 0 ? participantId : `participant-${index}`,
    order_index: index,
  }));
  value.public_turns = [{ ...value.public_turns[0], turn_index: 3 }];
  render(
    <LocaleProvider initialLocale="en">
      <BetaDebateStage
        api={api}
        debateId={debateId}
        detail={value}
        readOnly
        socketFactory={() => new IdleSocket()}
      />
    </LocaleProvider>,
  );
  const progress = screen.getByLabelText("Turn 4 of 12, disconnected");
  expect(progress.textContent).toBe("4/12");
  expect(progress.closest('[class*="streamHeader"]')).not.toBeNull();
  expect(progress.getAttribute("data-connected")).toBe("false");
  expect(screen.queryByText("Connected")).toBeNull();
  expect(screen.queryByText("unconnected")).toBeNull();
});
