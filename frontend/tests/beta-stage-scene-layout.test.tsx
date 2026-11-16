import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ScholarSceneProps } from "../components/stage3d/scholar-scene";
import { BetaDebateStage } from "../components/debate-beta/stage";
import type { DebateDetail } from "../lib/api";
import {
  musicStateForTests,
  resetBackgroundMusicForTests,
} from "../lib/background-music";
import {
  BETA_DOCK,
  BETA_NOTICES,
  BETA_PROVIDER_GATE_CARD,
  BETA_TOPIC,
  BETA_TRANSCRIPT_DRAWER,
} from "../components/debate-beta/stage/beta-chrome";

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
  useNoticeTrayAbove: () => undefined,
  NoticeTraySlot: () => null,
  RetryPill: ({ children, ...rest }: { children?: unknown }) => (
    <button type="button" {...rest}>
      {children as never}
    </button>
  ),
}));

afterEach(() => {
  cleanup();
  resetBackgroundMusicForTests();
  vi.restoreAllMocks();
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
  replayDebate: vi.fn(),
} as unknown as Parameters<typeof BetaDebateStage>[0]["api"];

function detail(): DebateDetail {
  return {
    id: debateId,
    course_id: courseId,
    topic: "Should the bench fill the screen?",
    background: "",
    status: "debate_finished",
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
      labels={{ transcript: "Public Debate", phaseFinished: "Completed" }}
      readOnly={readOnly}
      socketFactory={() => new IdleSocket()}
    />,
  );
}

describe("BetaDebateStage scene layout", () => {
  it("keeps configured stage music silent through entry, Start, unrelated gestures and reentry until its key is pressed", async () => {
    const play = vi
      .spyOn(HTMLMediaElement.prototype, "play")
      .mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    resetBackgroundMusicForTests({
      workspace: [],
      stage: ["/music/stage.mp3"],
    });
    const initial = detail();
    initial.status = "draft";
    initial.playback.status = "ready";
    const startDebate = vi.fn(() => new Promise<DebateDetail>(() => {}));
    const mount = () =>
      render(
        <BetaDebateStage
          api={{ ...api, startDebate }}
          debateId={debateId}
          detail={initial}
          socketFactory={() => new IdleSocket()}
        />,
      );
    const expectSilent = () => {
      expect(
        screen
          .getByRole("button", { name: "Play music" })
          .getAttribute("aria-pressed"),
      ).toBe("false");
      expect(musicStateForTests("stage")).toMatchObject({
        wanted: false,
        audible: false,
        playing: false,
        waiting: false,
      });
    };

    for (const visit of [1, 2]) {
      const view = mount();
      expectSilent();
      if (visit === 1) expect(musicStateForTests("stage").audio).toBeNull();
      else expect(musicStateForTests("stage").audio?.currentTime).toBe(0);
      expect(play).toHaveBeenCalledTimes(visit - 1);
      const start = screen.getByRole("button", { name: "Start debate" });
      fireEvent.pointerDown(start);
      fireEvent.pointerUp(start);
      fireEvent.click(start);
      expect(startDebate).toHaveBeenCalledTimes(visit);
      fireEvent.pointerDown(document.body);
      fireEvent.pointerUp(document.body);
      fireEvent.keyDown(document.body, { key: "a" });
      await act(async () => {});
      expectSilent();
      expect(play).toHaveBeenCalledTimes(visit - 1);

      await act(async () =>
        fireEvent.click(screen.getByRole("button", { name: "Play music" })),
      );
      expect(play).toHaveBeenCalledTimes(visit);
      expect(musicStateForTests("stage").wanted).toBe(true);
      const audio = musicStateForTests("stage").audio!;
      expect(audio.src).toContain("/music/stage.mp3");
      expect(audio.currentTime).toBe(0);
      audio.currentTime = 42;
      view.unmount();
    }
  });

  it("sends Start intent to the scene before the API or audio responds", () => {
    const initial = detail();
    initial.status = "draft";
    initial.playback.status = "ready";
    const startDebate = vi.fn(() => new Promise<DebateDetail>(() => {}));
    render(
      <BetaDebateStage
        api={{ ...api, startDebate }}
        debateId={debateId}
        detail={initial}
        socketFactory={() => new IdleSocket()}
      />,
    );
    expect(scholarSceneProps.at(-1)?.started).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Start debate" }));
    expect(startDebate).toHaveBeenCalledTimes(1);
    expect(scholarSceneProps.at(-1)?.started).toBe(true);
  });

  it("keeps Transcript above the title and recovery actions above Transcript", () => {
    const layer = (classes: string) => {
      const z = classes
        .split(/\s+/)
        .find((c) => /^z-(\[\d+\]|\d+|auto)$/.test(c));
      return z === "z-auto" ? NaN : Number(z?.replace(/^z-\[?(\d+)\]?$/, "$1"));
    };
    expect(BETA_NOTICES.split(/\s+/)).toContain("z-auto");
    expect(layer(BETA_TOPIC)).toBeLessThan(layer(BETA_TRANSCRIPT_DRAWER));
    expect(layer(BETA_TRANSCRIPT_DRAWER)).toBeLessThan(layer(BETA_DOCK));
    expect(layer(BETA_TRANSCRIPT_DRAWER)).toBeLessThan(
      layer(BETA_PROVIDER_GATE_CARD),
    );
  });

  it("keeps the full-viewport courtyard scene", () => {
    renderStage();

    const scene = screen.getByTestId("scholar-scene");
    expect(scene.getAttribute("data-layout")).toBe("preview");
    expect(scholarSceneProps[0].layout).toBe("preview");
    expect(
      screen.getByRole("heading", {
        name: "Should the bench fill the screen?",
      }),
    ).toBeTruthy();
  });

  it("separates fixed controls from the toggleable transcript and retains its heading", () => {
    renderStage(false);

    const scene = screen.getByTestId("scholar-scene");
    const dock = scene.nextElementSibling as HTMLElement;
    expect(dock.getAttribute("role")).toBe("group");
    expect(screen.getByRole("button", { name: "Next" })).toBeTruthy();
    expect(dock.querySelector("article")).toBeNull();
    const toggle = screen.getByRole("button", { name: "Transcript" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("complementary")).toBeNull();
    fireEvent.click(toggle);
    const drawer = screen.getByRole("complementary", { name: "Public Debate" });
    expect(
      screen.getByRole("heading", { name: "Public Debate Completed" }),
    ).toBeTruthy();
    const speeches = drawer.querySelectorAll("[data-stream-list] > article");
    expect(speeches).toHaveLength(1);
    expect(speeches[0].textContent).toContain("A full-bleed speech.");
    fireEvent.keyDown(drawer, { key: "Escape" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(toggle);
    fireEvent.click(toggle);
    fireEvent.click(toggle);
    expect(screen.queryByRole("complementary")).toBeNull();
  });
});
