import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AvatarConfig } from "../components/avatar";
import type { DebateDetail } from "../lib/api";
import { PlatformApiError } from "../lib/api";

const useSessionMock = vi.hoisted(() => vi.fn());
const replaceMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: replaceMock }),
  useParams: () => ({ debate_id: "20000000-0000-4000-8000-000000000001" }),
}));
vi.mock("../components/session-provider", () => ({
  RouteGuard: ({ children }: { children: ReactNode }) => children,
  useSession: useSessionMock,
}));
vi.mock("../components/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("../components/ui", () => ({
  ErrorNotice: () => <div>Error</div>,
  LoadingCard: () => <div>Loading</div>,
  Notice: ({
    children,
    action,
  }: {
    children?: ReactNode;
    action?: ReactNode;
  }) => (
    <div>
      {children}
      {action}
    </div>
  ),
  SectionCard: ({
    children,
    title,
  }: {
    children: ReactNode;
    title?: string;
  }) => (
    <section>
      {title ? <h2>{title}</h2> : null}
      {children}
    </section>
  ),
  StatusBadge: ({ status }: { status: string }) => <span>{status}</span>,
  PageIntro: ({ title, action }: { title: string; action?: ReactNode }) => (
    <header>
      <h1>{title}</h1>
      {action}
    </header>
  ),
}));
vi.mock("../lib/i18n", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/i18n")>()),
  useT: () => (key: string) => key,
}));
vi.mock("../components/avatar/avatar-preview", () => ({
  AvatarPreview: ({ fallbackLabel }: { fallbackLabel?: string }) => (
    <div>{fallbackLabel ?? "avatar"}</div>
  ),
}));

import TeacherDebateControlPage from "../app/teacher/debates/[debate_id]/control/page";

const debateId = "20000000-0000-4000-8000-000000000001";
const turnId = "40000000-0000-4000-8000-000000000001";
const participantId = "30000000-0000-4000-8000-000000000001";
const epoch = "50000000-0000-4000-8000-000000000001";

const avatarConfig: AvatarConfig = {
  template_id: "wave1-default-head",
  material_theme: "demo",
  eye_color: null,
  default_expression: "neutral",
  expression_strength: "medium",
  motion_style: "calm",
};

function runningDetail(): DebateDetail {
  return {
    id: debateId,
    course_id: "10000000-0000-4000-8000-000000000001",
    topic: "Should classrooms compare cultural perspectives?",
    background: "",
    status: "running",
    created_at: "2026-08-30T00:00:00Z",
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
    last_sequence: 0,
    rule_set_id: "ordered_multi_expert_mutual_learning_v1",
    round_count: 2,
    participants: [
      {
        id: participantId,
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
    ],
    public_turns: [
      {
        id: turnId,
        participant_id: participantId,
        round_no: 1,
        turn_index: 0,
        speech: "A published classroom speech.",
        retrieval_status: "matched",
        grounding_mode: "mixed",
        segment_turn: null,
        sources: [],
      },
    ],
    playback: {
      status: "waiting_next",
      mode: "live",
      current_turn_id: turnId,
      cursor_ms: 0,
      control_version: 1,
      next_turn_ready: true,
    },
    interaction_status: "closed",
    insight_status: "not_started",
    report_status: "not_started",
  };
}

type Listener = (event: Event) => void;

class ControlPageSocket {
  static instances: ControlPageSocket[] = [];

  readonly sent: string[] = [];
  private readonly listeners = new Map<string, Set<Listener>>();

  constructor(readonly url: string) {
    ControlPageSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {}

  addEventListener(type: string, listener: Listener): void {
    const listeners = this.listeners.get(type) ?? new Set<Listener>();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.get(type)?.delete(listener);
  }

  emit(type: "open" | "close" | "error" | "message", value?: unknown): void {
    const event =
      type === "message"
        ? new MessageEvent(type, { data: JSON.stringify(value) })
        : type === "close"
          ? ({ type, code: Number(value ?? 0) } as unknown as Event)
          : new Event(type);
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }
}

function acquired() {
  return {
    message_id: "91000000-0000-4000-8000-000000000001",
    message_type: "controller.acquired",
    result_version: 1,
    debate_id: debateId,
    occurred_at: "2026-08-30T00:00:00Z",
    controller_epoch: epoch,
    control_version: 1,
  };
}

function revoked(reason: "superseded" | "debate_terminal") {
  return {
    message_id: "91000000-0000-4000-8000-000000000002",
    message_type: "controller.revoked",
    result_version: 1,
    debate_id: debateId,
    occurred_at: "2026-08-30T00:00:00Z",
    controller_epoch: epoch,
    reason,
  };
}

function eventEnvelope(
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
    occurred_at: "2026-08-30T00:00:00Z",
    payload,
  };
}

function pageApi() {
  const detail = runningDetail();
  return {
    debate: vi.fn().mockResolvedValue(detail),
    course: vi.fn().mockResolvedValue({ current_audio_debate_id: debateId }),
    finishDebate: vi.fn().mockResolvedValue({
      ...detail,
      status: "stopped",
      playback: { ...detail.playback, status: "stopped" },
    }),
    startDebate: vi.fn(),
    advanceDebatePlayback: vi.fn(),
    pauseDebate: vi.fn(),
    resumeDebate: vi.fn(),
    replayDebate: vi.fn(),
    retryDebatePreparation: vi.fn().mockResolvedValue(detail.playback),
  };
}

async function mountWithController() {
  ControlPageSocket.instances = [];
  vi.stubGlobal("WebSocket", ControlPageSocket);
  const api = pageApi();
  useSessionMock.mockReturnValue({ api });
  render(<TeacherDebateControlPage />);
  await waitFor(() => expect(ControlPageSocket.instances).toHaveLength(1));
  const socket = ControlPageSocket.instances[0]!;
  socket.emit("open");
  socket.emit("message", acquired());
  const finish = await screen.findByRole("button", { name: /^End$/ });
  await waitFor(() => expect(finish).toHaveProperty("disabled", false));
  return { api, finish, socket };
}

function forceFinishHandler(finish: HTMLElement): void {
  finish.removeAttribute("disabled");
  fireEvent.click(finish);
}

afterEach(() => {
  cleanup();
  useSessionMock.mockReset();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Wave 3 control-page Finish authority gate", () => {
  it("redirects legacy debates to the immersive beta control page", async () => {
    replaceMock.mockReset();
    const api = pageApi();
    api.debate.mockResolvedValue(runningDetail());
    useSessionMock.mockReturnValue({ api });

    render(<TeacherDebateControlPage />);

    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith(
        `/teacher/debates-beta/${debateId}/control`,
      ),
    );
    expect(screen.queryByTestId("debate-preview")).toBeNull();
  });

  it("uses the teacher preview for the segments protocol and gates classroom access", async () => {
    const preview = runningDetail();
    preview.turn_protocol = "segments_v2";
    preview.preview = { prepared_turns: 1, expected_turns: 1, ready: true };
    preview.preview_turns = [
      {
        id: turnId,
        participant_id: participantId,
        round_no: 1,
        turn_index: 0,
        speech: "Saved teacher preview speech.",
        generation_status: "ready",
        audio_ready: true,
        segments: [],
        sources: [],
      },
    ];
    const api = pageApi();
    api.debate.mockResolvedValue(preview);
    useSessionMock.mockReturnValue({ api });

    render(<TeacherDebateControlPage />);

    expect(await screen.findByTestId("debate-preview")).toBeTruthy();
    expect(screen.getByText("Saved teacher preview speech.")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Immerse" }).getAttribute("href"),
    ).toBe(`/teacher/debates-beta/${debateId}/control`);
    expect(screen.queryByRole("button", { name: "End" })).toBeNull();
  });

  it("retries one failed preview turn with the saved control version", async () => {
    const preview = runningDetail();
    preview.turn_protocol = "segments_v2";
    preview.preview = { prepared_turns: 0, expected_turns: 1, ready: false };
    preview.preview_turns = [
      {
        id: turnId,
        participant_id: participantId,
        round_no: 1,
        turn_index: 0,
        speech: "Saved speech despite the audio failure.",
        generation_status: "failed",
        audio_ready: false,
        safe_error_code: "tts_failed",
        segments: [],
        sources: [],
      },
    ];
    const api = pageApi();
    api.debate.mockResolvedValue(preview);
    useSessionMock.mockReturnValue({ api });

    render(<TeacherDebateControlPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Retry turn" }));
    await waitFor(() =>
      expect(api.retryDebatePreparation).toHaveBeenCalledWith(
        debateId,
        { turn_id: turnId, expected_control_version: 1 },
        expect.anything(),
      ),
    );
  });

});
