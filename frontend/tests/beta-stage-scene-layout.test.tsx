import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ScholarSceneProps } from "../components/stage3d/scholar-scene";
import { BetaDebateStage } from "../components/debate-beta/stage";
import type { DebateDetail } from "../lib/api";

const scholarSceneProps: ScholarSceneProps[] = [];

vi.mock("../components/stage3d/scholar-scene", () => ({
  ScholarScene: (props: ScholarSceneProps) => {
    scholarSceneProps.push(props);
    return (
      <div
        data-testid="scholar-scene"
        data-layout={props.layout ?? "classroom"}
      >
        {props.overlay}
      </div>
    );
  },
}));
vi.mock("../components/debate-beta/stage/bubble-progress", () => ({
  bubbleLineFrom: (speech: string) => speech,
  bubbleProgressFrom: (speech: string) => speech,
}));
vi.mock("../components/ui", () => ({
  QrCode: ({ value }: { value: string }) => <div>{value}</div>,
}));

afterEach(() => {
  cleanup();
  scholarSceneProps.length = 0;
});

const debateId = "20000000-0000-4000-8000-000000000001";
const courseId = "10000000-0000-4000-8000-000000000002";
const participantId = "30000000-0000-4000-8000-000000000001";
const turnId = "40000000-0000-4000-8000-000000000001";

class IdleSocket {
  send = vi.fn();
  close = vi.fn();
  addEventListener = vi.fn();
  removeEventListener = vi.fn();
}

const api = {
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
} as unknown as Parameters<typeof BetaDebateStage>[0]["api"];

function detail(): DebateDetail {
  return {
    id: debateId,
    course_id: courseId,
    topic: "Should the bench fill the screen?",
    background: "",
    status: "running",
    created_at: "2026-09-07T00:00:00Z",
    audio_restore_needed: false,
    prepared_turns: 1,
    expected_turns: 1,
    preview: null,
    output_language: "en",
    turn_protocol: "segments_v2",
    preview_turns: [],
    final_input_frozen: false,
    stall: null,
    revision: 1,
    last_sequence: 1,
    rule_set_id: "ordered_multi_expert_mutual_learning_v1",
    round_count: 1,
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
    public_turns: [
      {
        id: turnId,
        participant_id: participantId,
        round_no: 1,
        turn_index: 0,
        speech: "A full-bleed speech.",
        retrieval_status: "matched",
        grounding_mode: "rag_grounded",
        audio_ready: true,
        segment_turn: {
          schema_version: "segment_turn_v2",
          segments: [
            { text: "A full-bleed speech.", source_ids: [], reply_to: null },
          ],
        },
        source_details: [],
        sources: [],
      },
    ],
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

function renderStage(readOnly = true) {
  return render(
    <BetaDebateStage
      api={api}
      debateId={debateId}
      detail={detail()}
      readOnly={readOnly}
      socketFactory={() => new IdleSocket()}
    />,
  );
}

describe("BetaDebateStage scene layout", () => {
  it("opts into the full-viewport preview courtyard scene", () => {
    renderStage();

    const scene = screen.getByTestId("scholar-scene");
    expect(scene.getAttribute("data-layout")).toBe("preview");
    expect(scholarSceneProps[0].layout).toBe("preview");
  });

  it("keeps the teacher operation panel rendered beside the scene", () => {
    renderStage(false);

    const scene = screen.getByTestId("scholar-scene");
    const panel = scene.nextElementSibling as HTMLElement;
    expect(panel.className).toContain("stageColumns");
    expect(panel.getAttribute("data-transcript-open")).toBe("false");
    const toggle = screen.getByRole("button", { name: "Published transcript" });
    expect(screen.getByRole("button", { name: "Next" })).toBeTruthy();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(panel.getAttribute("data-transcript-open")).toBe("true");
    expect(
      panel.querySelector("#beta-stage-transcript")?.hasAttribute("hidden"),
    ).toBe(false);
  });
});
