import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AvatarConfig } from "../components/avatar";
import type { DebateDetail, TeacherInteraction } from "../lib/api";
import { agentScores } from "../components/wave3/agent-scores";

const useSessionMock = vi.hoisted(() => vi.fn());
const reportPanelMock = vi.hoisted(() => vi.fn());

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.open = true;
    },
  });
});

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
  resolveBetaStageLabels: () => ({
    openInteraction: "Interact",
    hideInteraction: "Hide",
    interactionOpening: "Opening…",
  }),
}));
vi.mock("../components/report", () => ({
  ReportPanel: (props: unknown) => {
    reportPanelMock(props);
    return (
      <section data-testid="inline-report">
        <h2>Report</h2>
        <button type="button">Regenerate</button>
      </section>
    );
  },
}));
vi.mock("../components/ui", () => ({
  ErrorNotice: () => <div role="alert">Error</div>,
  LoadingCard: () => <div>Loading</div>,
}));
vi.mock("../components/locale", () => ({
  useLocale: () => ({ locale: "en" }),
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
const avatarConfig: AvatarConfig = {
  template_id: "wave1-default-head",
  material_theme: "demo",
  eye_color: null,
  default_expression: "neutral",
  expression_strength: "medium",
  motion_style: "calm",
};

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

function finishedSegmentsDetail(): DebateDetail {
  return {
    id: debateId,
    course_id: courseId,
    topic: "Should classrooms compare cultural perspectives?",
    background: "",
    status: "debate_finished",
    created_at: "2026-08-30T00:00:00Z",
    audio_restore_needed: false,
    prepared_turns: 4,
    expected_turns: 4,
    preview: null,
    output_language: "en",
    turn_protocol: "segments_v2",
    preview_turns: [],
    final_input_frozen: true,
    stall: null,
    revision: 1,
    last_sequence: 4,
    rule_set_id: "ordered_multi_expert_mutual_learning_v1",
    round_count: 2,
    participants,
    public_turns: completeTurns(),
    playback: {
      status: "completed",
      mode: "live",
      current_turn_id: null,
      cursor_ms: 0,
      control_version: 4,
      next_turn_ready: false,
    },
    interaction_status: "closed",
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
  detail = finishedSegmentsDetail(),
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
    regenerateReport: vi
      .fn()
      .mockResolvedValue({ generation_status: "generating" }),
    finishDebate: vi.fn(),
  };
}

function renderPage(api: ReturnType<typeof pageApi>) {
  useSessionMock.mockReturnValue({ api });
  return render(<TeacherDebateControlPage />);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("segments_v2 Bench Conclude and Report", () => {
  it("refreshes a stale closed window before Conclude without leaving the stage", async () => {
    const api = pageApi(interaction("closed"));
    renderPage(api);
    const conclude = await screen.findByRole("button", { name: "Conclude" });
    api.teacherInteraction
      .mockResolvedValueOnce(interaction("open"))
      .mockResolvedValueOnce(interaction("open"));
    fireEvent.click(conclude);
    expect(await screen.findByRole("dialog", { name: "Report" })).toBeTruthy();
    expect(api.openInteraction).not.toHaveBeenCalled();
    expect(api.closeInteraction).toHaveBeenCalledTimes(1);
    expect(api.regenerateReport).toHaveBeenCalledWith(
      debateId,
      expect.objectContaining({ initial: true }),
    );
  });

  it("opens an already-finalized report discovered on Conclude", async () => {
    const api = pageApi(interaction("closed"));
    renderPage(api);
    const conclude = await screen.findByRole("button", { name: "Conclude" });
    api.teacherInteraction.mockResolvedValue(interaction("finalized"));
    fireEvent.click(conclude);
    expect(await screen.findByRole("dialog", { name: "Report" })).toBeTruthy();
    expect(api.openInteraction).not.toHaveBeenCalled();
    expect(api.closeInteraction).not.toHaveBeenCalled();
    expect(api.regenerateReport).toHaveBeenCalledWith(
      debateId,
      expect.objectContaining({ initial: true }),
    );
  });

  it("uses public paragraph grades for Conclude totals and never counts a replay twice", async () => {
    const detail = finishedSegmentsDetail();
    const first = detail.public_turns[0]!;
    first.segment_turn = {
      schema_version: "segment_turn_v2",
      segments: [
        {
          text: "The record names the agreed day.",
          source_ids: ["source-1"],
          reply_to: null,
          support_mode: "direct",
        },
        {
          text: "The shared practice provides background.",
          source_ids: ["source-1"],
          reply_to: null,
          support_mode: "contextual",
        },
        {
          text: "I suggest discussing a change.",
          source_ids: [],
          reply_to: null,
          support_mode: "no_match",
        },
      ],
    };
    expect(
      agentScores(detail.participants, [...detail.public_turns, first])[0]
        ?.value,
    ).toBe(7);
    expect(
      agentScores(detail.participants, detail.public_turns)[1]?.value,
    ).toBe(0);
    const api = pageApi(interaction("open"), interaction("finalized"), detail);
    renderPage(api);
    fireEvent.click(await screen.findByRole("button", { name: "Conclude" }));
    await screen.findByRole("dialog", { name: "Report" });
    expect(screen.getByRole("heading", { name: "Evaluation" })).toBeTruthy();
    expect(screen.queryByText(/unscored/i)).toBeNull();
    expect(screen.getByText("No match +0")).toBeTruthy();
    expect(screen.getByText("Direct evidence +5")).toBeTruthy();
    expect(api.closeInteraction).toHaveBeenCalledTimes(1);
  });

  it("toggles the same join code without closing or reopening classroom messages", async () => {
    const detail = { ...finishedSegmentsDetail(), status: "running" as const };
    detail.final_input_frozen = false;
    detail.playback = {
      ...detail.playback,
      status: "playing",
      current_turn_id: detail.public_turns[0]?.id ?? null,
    };
    const api = pageApi(interaction("closed"), interaction("closed"), detail);
    renderPage(api);
    const toggle = await screen.findByRole("button", { name: "Interact" });
    fireEvent.click(toggle);
    expect(await screen.findByRole("button", { name: "Hide" })).toBe(toggle);
    const url = screen.getByRole("img", { name: "Scan to join" }).textContent;
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle);
    expect(screen.queryByRole("img", { name: "Scan to join" })).toBeNull();
    expect(screen.getByTestId("beta-stage").getAttribute("data-join-url")).toBe(
      url,
    );
    expect(screen.getByRole("button", { name: "Interact" })).toBe(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(screen.getByRole("img", { name: "Scan to join" }).textContent).toBe(
      url,
    );
    expect(api.openInteraction).toHaveBeenCalledTimes(1);
    expect(api.closeInteraction).not.toHaveBeenCalled();
  });

  it("restores the existing classroom URL after a reload without a new open request", async () => {
    const detail = { ...finishedSegmentsDetail(), status: "running" as const };
    detail.final_input_frozen = false;
    detail.playback = {
      ...detail.playback,
      status: "playing",
      current_turn_id: detail.public_turns[0]?.id ?? null,
    };
    const api = pageApi(interaction("open"), interaction("open"), detail);
    renderPage(api);
    const toggle = await screen.findByRole("button", { name: "Interact" });
    expect(screen.queryByRole("img", { name: "Scan to join" })).toBeNull();
    fireEvent.click(toggle);
    expect(screen.getByRole("img", { name: "Scan to join" }).textContent).toBe(
      interaction("open").public_url,
    );
    expect(api.openInteraction).not.toHaveBeenCalled();
    expect(api.closeInteraction).not.toHaveBeenCalled();
  });

  it("does not offer Interact after final input has been frozen", async () => {
    const detail = finishedSegmentsDetail();
    detail.status = "running";
    detail.playback.status = "playing";
    detail.playback.current_turn_id = detail.public_turns[0]?.id ?? null;
    const api = pageApi(
      interaction("closed"),
      interaction("finalized"),
      detail,
    );
    renderPage(api);

    await waitFor(() => expect(api.teacherInteraction).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Interact" })).toBeNull();
    expect(api.openInteraction).not.toHaveBeenCalled();
  });

  it("closes an already-open classroom and opens the Report dialog", async () => {
    const api = pageApi(interaction("open"));
    renderPage(api);

    const conclude = await screen.findByRole("button", { name: "Conclude" });
    fireEvent.click(conclude);

    await waitFor(() => expect(api.closeInteraction).toHaveBeenCalledTimes(1));
    expect(api.openInteraction).not.toHaveBeenCalled();
    expect(api.closeInteraction).toHaveBeenCalledWith(
      debateId,
      expect.objectContaining({ idempotency: expect.anything() }),
    );
    expect(await screen.findByTestId("inline-report")).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "Report" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Interaction" })).toBeNull();
    expect(reportPanelMock).toHaveBeenCalled();
  });

  it("opens an unopened classroom then closes it with separate durable keys", async () => {
    const api = pageApi(interaction("closed"));
    renderPage(api);

    const conclude = await screen.findByRole("button", { name: "Conclude" });
    fireEvent.click(conclude);
    fireEvent.click(conclude);

    await waitFor(() => expect(api.closeInteraction).toHaveBeenCalledTimes(1));
    expect(api.openInteraction).toHaveBeenCalledTimes(1);
    const openKey = api.openInteraction.mock.calls[0]?.[1]?.idempotency;
    const closeKey = api.closeInteraction.mock.calls[0]?.[1]?.idempotency;
    expect(openKey).toEqual(expect.anything());
    expect(closeKey).toEqual(expect.anything());
    expect(closeKey).not.toBe(openKey);
    expect(await screen.findByTestId("inline-report")).toBeTruthy();
  });

  it("restores Conclude after refresh to reopen the report without closing interaction again", async () => {
    const api = pageApi(interaction("finalized"));
    renderPage(api);

    const report = await screen.findByRole("button", {
      name: "Conclude",
    });
    expect(screen.queryByTestId("inline-report")).toBeNull();
    fireEvent.click(report);
    expect(await screen.findByRole("dialog", { name: "Report" })).toBeTruthy();
    fireEvent(
      screen.getByRole("dialog", { name: "Report" }),
      new Event("close"),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(report);
    expect(await screen.findByRole("dialog", { name: "Report" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Report" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Evaluation" })).toBeNull();
    expect(api.closeInteraction).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "Interaction" })).toBeNull();
  });
});

it("sorts evaluation by descending score and keeps names without numbering", () => {
  const detail = finishedSegmentsDetail();
  const low = detail.participants[0];
  const high = detail.participants[1];
  const turns = [
    {
      ...detail.public_turns[0],
      id: "low",
      participant_id: low.id,
      segment_turn: {
        schema_version: "segment_turn_v2",
        segments: [
          {
            text: "Low",
            source_ids: [],
            reply_to: null,
            support_mode: "no_match",
          },
        ],
      },
    },
    {
      ...detail.public_turns[1],
      id: "high",
      participant_id: high.id,
      segment_turn: {
        schema_version: "segment_turn_v2",
        segments: [
          {
            text: "High",
            source_ids: ["S1"],
            reply_to: null,
            support_mode: "direct",
          },
        ],
      },
    },
  ] as DebateDetail["public_turns"];
  const data = agentScores(detail.participants, turns);
  expect(data.map((row) => [row.label, row.value])).toEqual([
    [high.agent_name, 5],
    [low.agent_name, 0],
  ]);
});
