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

vi.mock("next/navigation", () => ({
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
  PageIntro: ({ title, action }: { title: string; action?: ReactNode }) => (
    <header>
      <h1>{title}</h1>
      {action}
    </header>
  ),
}));
vi.mock("../components/locale", () => ({
  useT: () => (key: string) => key,
  useLocale: () => ({ locale: "en" }),
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
    status: "running",
    created_at: "2026-08-30T00:00:00Z",
    prepared_turns: 0,
    expected_turns: 0,
    revision: 1,
    last_sequence: 0,
    rule_set_id: "ordered_multi_agent_rounds_demo_v1",
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
        sources: [],
      },
    ],
    playback: {
      status: "waiting_next",
      mode: "live",
      current_turn_id: turnId,
      cursor_ms: 0,
      playback_rate: 1,
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
  it("keeps Finish blocked after superseded even when public paused state advances", async () => {
    const { api, finish, socket } = await mountWithController();
    socket.emit("message", revoked("superseded"));
    forceFinishHandler(finish);
    expect(api.finishDebate).not.toHaveBeenCalled();
    socket.emit(
      "message",
      eventEnvelope("playback.paused", 1, {
        turn_id: turnId,
        cursor_ms: 100,
        control_version: 2,
      }),
    );

    await waitFor(() => expect(finish).toHaveProperty("disabled", true));
    expect(screen.getByText(/another teacher page has control/)).toBeTruthy();
    forceFinishHandler(finish);
    expect(api.finishDebate).not.toHaveBeenCalled();
  });

  it.each([
    ["4401", /please sign in again/],
    ["4403", /classroom address does not match/],
    ["terminal", /debate is already ending/],
    ["network", /connection is restored/],
    ["sequence", /classroom state is resynchronized/],
  ])("fails Finish closed for %s", async (reason, copy) => {
    const { api, finish, socket } = await mountWithController();
    if (reason === "4401" || reason === "4403") {
      socket.emit("error");
      socket.emit("close", Number(reason));
    } else if (reason === "terminal") {
      socket.emit("message", revoked("debate_terminal"));
    } else if (reason === "network") {
      socket.emit("close", 1006);
    } else {
      socket.emit(
        "message",
        eventEnvelope("playback.paused", 2, {
          turn_id: turnId,
          control_version: 2,
        }),
      );
    }

    forceFinishHandler(finish);
    expect(api.finishDebate).not.toHaveBeenCalled();
    await waitFor(() => expect(finish).toHaveProperty("disabled", true));
    expect(screen.getByText(copy)).toBeTruthy();
    forceFinishHandler(finish);
    expect(api.finishDebate).not.toHaveBeenCalled();
  });

  it("allows active controller Finish exactly once", async () => {
    const { api, finish } = await mountWithController();
    fireEvent.click(finish);
    fireEvent.click(finish);
    await waitFor(() => expect(api.finishDebate).toHaveBeenCalledTimes(1));
  });

  it("blocks Finish synchronously while Next is in flight", async () => {
    const { api, finish } = await mountWithController();
    let releaseNext!: (value: DebateDetail) => void;
    api.advanceDebatePlayback.mockReturnValue(
      new Promise<DebateDetail>((resolve) => {
        releaseNext = resolve;
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    forceFinishHandler(finish);
    expect(api.finishDebate).not.toHaveBeenCalled();

    releaseNext(runningDetail());
    await waitFor(() => expect(finish).toHaveProperty("disabled", false));
  });

  it("keeps Finish hidden while a finished debate replay waits for Next", async () => {
    ControlPageSocket.instances = [];
    vi.stubGlobal("WebSocket", ControlPageSocket);
    const replay = runningDetail();
    replay.status = "completed";
    replay.playback = {
      ...replay.playback,
      status: "playing",
      mode: "replay",
      current_turn_id: turnId,
      next_turn_ready: false,
    };
    const api = pageApi();
    api.debate.mockResolvedValue(replay);
    useSessionMock.mockReturnValue({ api });
    render(<TeacherDebateControlPage />);

    await waitFor(() => expect(ControlPageSocket.instances).toHaveLength(1));
    const socket = ControlPageSocket.instances[0]!;
    socket.emit("open");
    socket.emit("message", acquired());
    socket.emit(
      "message",
      eventEnvelope("replay.started", 1, {
        scope: "all",
        turn_id: turnId,
        control_version: 1,
      }),
    );
    socket.emit(
      "message",
      eventEnvelope("playback.waiting_next", 2, {
        mode: "replay",
        completed_turn_id: turnId,
        control_version: 1,
        next_turn_ready: true,
      }),
    );

    await waitFor(() =>
      expect(
        document.querySelector('[data-classroom-phase="waiting"]'),
      ).toBeTruthy(),
    );
    expect(screen.getByRole("button", { name: "Next" })).toHaveProperty(
      "disabled",
      false,
    );
    expect(screen.queryByRole("button", { name: "End" })).toBeNull();
    expect(
      screen.queryByText(
        "Finish is available only while the classroom status is Waiting.",
      ),
    ).toBeNull();
  });

  it("keeps page Finish closed when manual reconnect snapshot returns HTTP 401", async () => {
    const { api, finish, socket } = await mountWithController();
    api.debate.mockRejectedValue(
      new PlatformApiError(401, "Authentication is required."),
    );
    socket.emit("close", 1006);
    fireEvent.click(await screen.findByRole("button", { name: /Reconnect/ }));

    expect(
      await screen.findAllByText(/Finish unavailable: please sign in again/),
    ).not.toHaveLength(0);
    await waitFor(() => expect(finish).toHaveProperty("disabled", true));
    expect(screen.queryByRole("button", { name: /Reconnect/ })).toBeNull();
    expect(screen.queryByText("Authentication is required.")).toBeNull();
    forceFinishHandler(finish);
    expect(api.finishDebate).not.toHaveBeenCalled();
  });
});
