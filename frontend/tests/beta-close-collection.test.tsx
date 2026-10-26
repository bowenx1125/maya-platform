import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DebateDetail, TeacherInteraction } from "../lib/api";

const useSessionMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useParams: () => ({ debate_id: "20000000-0000-4000-8000-000000000001" }),
}));
vi.mock("../components/session-provider", () => ({
  RouteGuard: ({ children }: { children: ReactNode }) => children,
  useSession: useSessionMock,
}));
vi.mock("../components/debate-beta/stage", () => ({
  BetaDebateStage: ({
    headerActions,
    joinUrl,
    joinCodeVisible,
  }: {
    headerActions?: ReactNode | ((replayButton: ReactNode) => ReactNode);
    joinUrl?: string | null;
    joinCodeVisible?: boolean;
  }) => (
    <section data-testid="beta-stage" data-join-url={joinUrl}>
      {typeof headerActions === "function"
        ? headerActions(<button type="button">Replay</button>)
        : headerActions}
      {joinUrl && joinCodeVisible ? (
        <div id="classroom-join-code" role="img" aria-label="Scan to join">
          {joinUrl}
        </div>
      ) : null}
    </section>
  ),
  defaultBetaStageLabels: {
    openInteraction: "Interact",
    hideInteraction: "Hide",
    interactionOpening: "Opening…",
  },
}));
vi.mock("../components/report", () => ({
  ReportPanel: () => (
    <section data-testid="inline-report">
      <h2>Report</h2>
    </section>
  ),
}));
vi.mock("../components/ui", () => ({
  ErrorNotice: () => <div role="alert">Error</div>,
  LoadingCard: () => <div>Loading</div>,
}));
vi.mock("../lib/i18n", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/i18n")>()),
  useT: () => (key: string) =>
    ({
      debateBack: "Back",
      debateStageTitle: "Debate",
      debateStageDescription: "",
      debateStart: "Start",
      debateReplayTurn: "Replay turn",
      debateReplayAll: "Replay whole debate",
      debatePartial: "Partial",
      debateTranscript: "Public Debate",
      debateSources: "Sources",
      debateNoSources: "No sources",
      debateRound: "Round",
      debateCurrent: "Current",
      debatePrepared: "Prepared",
      debateComplete: "Complete",
      debateStopped: "Stopped",
      debateFailed: "Failed",
      statusPreparing: "Preparing",
      statusReady: "Ready",
      statusPlaying: "Playing",
      statusPaused: "Paused",
      debateWaitingNext: "Waiting",
      debatePhaseOpening: "Opening",
      debatePhaseExchange: "Exchange",
      debatePhaseFinalIntegration: "Final integration",
      debateWaitingForAudio: "Waiting for audio",
      debateConnectionReady: "Connected",
      debateConnectionReconnecting: "Reconnecting",
      debateConnectionDisconnected: "Disconnected",
      debateConnectionSequenceGap: "Resyncing",
      debateConnectionSessionExpired: "Sign in again",
      debateConnectionOriginMismatch: "Origin mismatch",
      debateConnectionSuperseded: "Another teacher has control",
      debateConnectionError: "Connection error",
      debateControllerWaiting: "Waiting for teacher control",
      debateControlBusy: "Working",
      debateRetryReason: "Retry",
      debateConnectionSignIn: "Sign in",
      debateConnectionReload: "Reload",
      debateRegenerate: "Regenerate",
      debateProviderSetupIncomplete: "Provider setup incomplete",
      debateProviderGateTitle: "Provider approval",
      debateProviderGateLoading: "Loading",
      debateProviderGateEmpty: "No pending approvals",
      debateProviderGateReview: "Review",
      debateProviderGateReviewAll: "Review all",
      debateProviderGateConfirmed: "Confirmed",
      debateProviderGateRetry: "Retry",
      debateNoPublishedSpeech: "No published speech",
      errorAudioNotRetained: "Audio not retained",
      debateSelectedTurn: "Selected turn",
      debateReplaceAudioConfirm: "Replace audio?",
      debateAudioLabel: "Debate audio",
      debates: "Debates",
      wave3Title: "Interaction",
    })[key] ?? key,
}));

import TeacherDebateControlPage from "../app/teacher/debates-beta/[debate_id]/control/page";

const debateId = "20000000-0000-4000-8000-000000000001";
const courseId = "10000000-0000-4000-8000-000000000002";
const avatarConfig = {
  template_id: "wave1-default-head",
  material_theme: "demo",
  eye_color: null,
  default_expression: "neutral",
  expression_strength: "medium",
  motion_style: "calm",
} as const;

const participants = [
  {
    id: "30000000-0000-4000-8000-000000000001",
    slot: "A" as const,
    order_index: 0,
    agent_id: "60000000-0000-4000-8000-000000000001",
    agent_name: "Bowen",
    agent_version_id: "70000000-0000-4000-8000-000000000001",
    version_label: "V1.0",
    knowledge_snapshot_id: "80000000-0000-4000-8000-000000000001",
    avatar_config: avatarConfig,
    effective_voice_profile_id: null,
    voice_fallback_active: true,
    stance_mode: "assigned" as const,
    initial_stance: "support" as const,
    current_stance: "support" as const,
  },
  {
    id: "30000000-0000-4000-8000-000000000002",
    slot: "B" as const,
    order_index: 1,
    agent_id: "60000000-0000-4000-8000-000000000002",
    agent_name: "Kaikai",
    agent_version_id: "70000000-0000-4000-8000-000000000002",
    version_label: "V1.0",
    knowledge_snapshot_id: "80000000-0000-4000-8000-000000000002",
    avatar_config: avatarConfig,
    effective_voice_profile_id: null,
    voice_fallback_active: true,
    stance_mode: "assigned" as const,
    initial_stance: "oppose" as const,
    current_stance: "oppose" as const,
  },
];

function completeTurns() {
  return participants.flatMap((participant, participantIndex) =>
    [1, 2].map((roundNo, roundIndex) => ({
      id: `40000000-0000-4000-8000-${String(participantIndex * 2 + roundIndex + 1).padStart(12, "0")}`,
      participant_id: participant.id,
      round_no: roundNo,
      turn_index: participantIndex + roundIndex * participants.length,
      speech: `${participant.agent_name} round ${roundNo}`,
      retrieval_status: "matched" as const,
      grounding_mode: "mixed" as const,
      segment_turn: {
        schema_version: "segment_turn_v2" as const,
        segments: [
          {
            text: `${participant.agent_name} round ${roundNo}`,
            source_ids: [],
            reply_to: null,
          },
        ],
      },
      source_details: [],
      sources: [],
    })),
  );
}

/** Running debate with playback mid-stream: Conclude must never be offered. */
function runningSegmentsDetail(): DebateDetail {
  return {
    id: debateId,
    course_id: courseId,
    topic: "Should classrooms compare cultural perspectives?",
    background: "",
    status: "running",
    created_at: "2026-08-30T00:00:00Z",
    audio_restore_needed: false,
    prepared_turns: 4,
    expected_turns: 4,
    preview: null,
    output_language: "en",
    turn_protocol: "segments_v2",
    preview_turns: [],
    final_input_frozen: false,
    stall: null,
    revision: 1,
    last_sequence: 2,
    rule_set_id: "ordered_multi_expert_mutual_learning_v1",
    round_count: 2,
    participants,
    public_turns: completeTurns(),
    playback: {
      status: "playing",
      mode: "live",
      current_turn_id: "40000000-0000-4000-8000-000000000001",
      cursor_ms: 0,
      control_version: 4,
      next_turn_ready: false,
    },
    interaction_status: "open",
    insight_status: "not_started",
    report_status: "not_started",
  };
}

function interaction(status: TeacherInteraction["status"]): TeacherInteraction {
  return {
    status,
    public_url:
      status === "open" ? "https://classroom.example/join-token" : null,
    votes: [],
    barrages: [],
  } as TeacherInteraction;
}

function pageApi(
  initial: TeacherInteraction,
  afterClose = interaction("finalized"),
  detail: DebateDetail = runningSegmentsDetail(),
) {
  let current = initial;
  return {
    debate: vi.fn().mockResolvedValue(detail),
    course: vi.fn().mockResolvedValue({ current_audio_debate_id: debateId }),
    teacherInteraction: vi.fn().mockImplementation(async () => current),
    openInteraction: vi.fn().mockImplementation(async () => {
      current = interaction("open");
      return current;
    }),
    closeInteraction: vi.fn().mockImplementation(async () => {
      current = afterClose;
      return current;
    }),
    regenerateReport: vi.fn(),
    finishDebate: vi.fn(),
  };
}

function renderPage(api: ReturnType<typeof pageApi>) {
  useSessionMock.mockReturnValue({ api });
  return render(<TeacherDebateControlPage />);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("segments_v2 interaction dock (A1: no Close collection)", () => {
  it("toggles the join code with Hide and never closes the collection", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const api = pageApi(interaction("open"));
    renderPage(api);
    const toggle = await screen.findByRole("button", { name: "Interact" });
    fireEvent.click(toggle);
    expect(screen.getByRole("img", { name: "Scan to join" })).toBeTruthy();
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle);
    expect(screen.queryByRole("img", { name: "Scan to join" })).toBeNull();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(api.closeInteraction).not.toHaveBeenCalled();
    expect(api.openInteraction).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("does not expose Close collection — collection stays open by default", async () => {
    const api = pageApi(interaction("open"));
    renderPage(api);
    await screen.findByRole("button", { name: "Interact" });
    expect(
      screen.queryByRole("button", { name: "Close collection" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Closing…" }),
    ).toBeNull();
    expect(api.closeInteraction).not.toHaveBeenCalled();
  });
});
