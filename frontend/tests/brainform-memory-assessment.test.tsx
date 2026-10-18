import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  api: {} as Record<string, ReturnType<typeof vi.fn>>,
  role: "student",
  search: "",
  userId: "abcdefab-cdef-4abc-8def-abcdefabcdef",
  courseId: "44444444-4444-4444-8444-444444444444",
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    identityGeneration: 1,
    user: {
      id: state.userId,
      courses: [
        { course_id: state.courseId, role: state.role },
        { course_id: "course-teacher", role: "teacher" },
      ],
      groups: [],
    },
  }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => `/${state.role}/chat`,
  useSearchParams: () => new URLSearchParams(window.location.search),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

import { AgentChat } from "../components/agent-chat";
import { LocaleProvider } from "../components/locale";
import { resetChatRequestIdentity } from "../lib/chat-request-store";

const actionId = "11111111-1111-4111-8111-111111111111";
const requestId = "22222222-2222-4222-8222-222222222222";
const conversationId = "33333333-3333-4333-8333-333333333333";
const courseId = "44444444-4444-4444-8444-444444444444";
const agentId = "55555555-5555-4555-8555-555555555555";
const agent = {
  agent_id: agentId,
  version_id: "66666666-6666-4666-8666-666666666666",
  course_id: courseId,
  name: "Socrates",
  version_label: "V1",
  avatar_config: {},
  available: true,
};

function session(turns: unknown[] = [], revision = 0) {
  return {
    id: conversationId,
    agent,
    revision,
    turns,
    created_at: "2026-10-04T00:00:00Z",
    read_only: false,
    can_send: true,
  };
}

function readyMemorySession(reply: string) {
  return session(
    [
      {
        id: requestId,
        user_text: "你目前记得我们之前聊过什么？",
        assistant_text: reply,
        mode: "mock",
        state: "ready",
        sources: [],
        safe_error_code: null,
      },
    ],
    1,
  );
}

function assessmentResult(
  status: "in_progress" | "paused",
  responseKey:
    "assessment.progress" | "assessment.paused" | "assessment.resumed",
) {
  return {
    disposition: "read" as const,
    response_key: responseKey,
    context: {
      attempt: {
        id: "88888888-8888-4888-8888-888888888888",
        activity_id: "99999999-9999-4999-8999-999999999999",
        conversation_id: conversationId,
        chat_visibility: "private" as const,
        status,
        revision: 3,
      },
      progress: {
        attempt_id: "88888888-8888-4888-8888-888888888888",
        status,
        question_count: 4,
        presented_count: 2,
        resolved_count: 1,
        answered_count: 1,
        skipped_count: 0,
        current_ordinal: 2,
        current_question_version_id: "question-version-2",
      },
      current_question: {
        ordinal: 2,
        question_version_id: "question-version-2",
        prompt: "What did the second question ask?",
      },
      canonical_conversation_id: conversationId,
      redirect_to_original_conversation: false,
    },
    answers: [
      {
        question_ordinal: 1,
        question_version_id: "question-version-1",
        answer_text: "My original answer",
        created_at: "2026-10-04T00:00:00Z",
      },
    ],
  };
}

function renderChat() {
  return render(
    <LocaleProvider initialLocale="en">
      <AgentChat />
    </LocaleProvider>,
  );
}

function setMemoryUrl(overrides: Record<string, string> = {}) {
  const params = new URLSearchParams({
    memory_action_id: actionId,
    memory_actor_id: state.userId,
    memory_course_id: courseId,
    memory_source_kind: "agent",
    memory_source_id: agentId,
    ...overrides,
  });
  window.history.replaceState(
    {},
    "",
    `/${state.role}/chat?${params.toString()}`,
  );
}

beforeEach(() => {
  state.role = "student";
  state.userId = "abcdefab-cdef-4abc-8def-abcdefabcdef";
  state.courseId = courseId;
  state.api = {
    chatAgents: vi.fn().mockResolvedValue([agent]),
    conversations: vi.fn().mockResolvedValue([]),
    conversationSessions: vi.fn().mockResolvedValue([]),
    memoryEntry: vi.fn().mockResolvedValue({
      action_id: actionId,
      conversation_id: conversationId,
      request_id: requestId,
      message: "你目前记得我们之前聊过什么？",
      session: session(),
    }),
    createConversation: vi.fn(),
    streamConversation: vi.fn().mockResolvedValue({
      session: session(
        [
          {
            id: requestId,
            user_text: "你目前记得我们之前聊过什么？",
            assistant_text: "A saved memory reply.",
            mode: "mock",
            state: "ready",
            sources: [],
            safe_error_code: null,
          },
        ],
        1,
      ),
    }),
    conversationSession: vi.fn().mockResolvedValue(session()),
    streamTeamConversation: vi.fn(),
    controlConversationTurn: vi.fn(),
    assessmentAttemptAction: vi.fn(),
    deleteConversation: vi.fn(),
  };
  window.history.replaceState({}, "", `/${state.role}/chat`);
  sessionStorage.clear();
  resetChatRequestIdentity();
});

afterEach(() => {
  cleanup();
  resetChatRequestIdentity();
  sessionStorage.clear();
});

describe("Brainform Memory and Assessment Chat path", () => {
  it("resolves the selected owner Agent and sends the server request ID exactly once", async () => {
    setMemoryUrl();
    state.api.conversationSession.mockResolvedValueOnce(
      readyMemorySession("A saved memory reply."),
    );
    renderChat();

    await waitFor(() => expect(state.api.memoryEntry).toHaveBeenCalledTimes(1));
    expect(state.api.memoryEntry).toHaveBeenCalledWith({
      action_id: actionId,
      course_id: courseId,
      source: { kind: "agent", agent_id: agentId },
    });
    await waitFor(() =>
      expect(state.api.streamConversation).toHaveBeenCalledTimes(1),
    );
    expect(state.api.streamConversation).toHaveBeenCalledWith(
      conversationId,
      {
        request_id: requestId,
        expected_revision: 0,
        message: "你目前记得我们之前聊过什么？",
      },
      expect.any(Object),
    );
    expect(await screen.findByText("A saved memory reply.")).toBeTruthy();
  });

  it("observes an existing action turn after navigation recovery without streaming it again", async () => {
    setMemoryUrl();
    const recovered = session(
      [
        {
          id: requestId,
          user_text: "你目前记得我们之前聊过什么？",
          assistant_text: "Recovered saved memory.",
          mode: "mock",
          state: "ready",
          sources: [],
          safe_error_code: null,
        },
      ],
      1,
    );
    state.api.memoryEntry.mockResolvedValueOnce({
      action_id: actionId,
      conversation_id: conversationId,
      request_id: requestId,
      message: "你目前记得我们之前聊过什么？",
      session: recovered,
    });
    renderChat();

    expect(await screen.findByText("Recovered saved memory.")).toBeTruthy();
    expect(state.api.streamConversation).not.toHaveBeenCalled();
  });

  it("fails closed when the URL course does not belong to the current route role", async () => {
    setMemoryUrl({ memory_course_id: "77777777-7777-4777-8777-777777777777" });
    renderChat();

    expect(await screen.findByText(/Memory link is incomplete/)).toBeTruthy();
    expect(state.api.memoryEntry).not.toHaveBeenCalled();
    expect(state.api.streamConversation).not.toHaveBeenCalled();
  });

  it("does not send an old Memory action after the authenticated actor changes", async () => {
    setMemoryUrl();
    state.userId = "fedcbafe-dcba-4fed-8cba-fedcbafedcba";
    renderChat();

    expect(await screen.findByText(/Memory link is incomplete/)).toBeTruthy();
    expect(state.api.memoryEntry).not.toHaveBeenCalled();
    expect(state.api.streamConversation).not.toHaveBeenCalled();
  });

  it("keeps paused assessment recovery in the ordinary Chat history and composer", async () => {
    const paused = session(
      [
        {
          id: requestId,
          user_text: "查我的原记录",
          assistant_text:
            "已暂停并保留你的作答。进度：已回答 1/4 题。原始回答：My original answer。你可以直接继续。",
          mode: "mock",
          state: "ready",
          sources: [],
          safe_error_code: null,
          assessment_result: assessmentResult("paused", "assessment.paused"),
        },
      ],
      1,
    );
    const continued = session(
      [
        ...paused.turns,
        {
          id: "77777777-7777-4777-8777-777777777777",
          user_text: "继续",
          assistant_text:
            "已继续。进度：已回答 1/4 题。第 2 题：What did the second question ask?",
          mode: "mock",
          state: "ready",
          sources: [],
          safe_error_code: null,
          assessment_result: assessmentResult(
            "in_progress",
            "assessment.resumed",
          ),
        },
      ],
      2,
    );
    state.api.conversationSessions.mockResolvedValueOnce([paused]);
    state.api.streamConversation.mockResolvedValueOnce({
      session: continued,
    });
    renderChat();

    expect(await screen.findByText(/已暂停并保留你的作答/)).toBeTruthy();
    expect(screen.getByText(/My original answer/)).toBeTruthy();
    expect(screen.getByText(/已回答 1\/4 题/)).toBeTruthy();
    expect(screen.queryByText(/assessment\.paused|88888888/)).toBeNull();
    expect(
      screen.queryByRole("button", { name: /pause assessment/i }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: /resume assessment/i }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: /abandon assessment/i }),
    ).toBeNull();

    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "继续" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(/已继续/)).toBeTruthy();
    expect(screen.getByText(/What did the second question ask/)).toBeTruthy();
    expect(state.api.streamConversation).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({ message: "继续", expected_revision: 1 }),
      expect.any(Object),
    );
    expect(state.api.assessmentAttemptAction).not.toHaveBeenCalled();
    expect(state.api.controlConversationTurn).not.toHaveBeenCalled();
  });

  it("sends a natural-language pause through the ordinary Agent Chat composer", async () => {
    const active = session(
      [
        {
          id: requestId,
          user_text: "这是我的作答",
          assistant_text:
            "已收到。进度：已回答 1/4 题。第 2 题：What did the second question ask?",
          mode: "mock",
          state: "ready",
          sources: [],
          safe_error_code: null,
          assessment_result: assessmentResult(
            "in_progress",
            "assessment.progress",
          ),
        },
      ],
      1,
    );
    const paused = session(
      [
        ...active.turns,
        {
          id: "77777777-7777-4777-8777-777777777777",
          user_text: "暂停",
          assistant_text: "已暂停并保留你的作答。你可以之后直接发送“继续”。",
          mode: "mock",
          state: "ready",
          sources: [],
          safe_error_code: null,
          assessment_result: assessmentResult("paused", "assessment.paused"),
        },
      ],
      2,
    );
    state.api.conversationSessions.mockResolvedValueOnce([active]);
    state.api.streamConversation.mockResolvedValueOnce({
      session: paused,
    });
    renderChat();

    expect(await screen.findByText(/第 2 题/)).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "暂停" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(/已暂停并保留你的作答/)).toBeTruthy();
    expect(state.api.streamConversation).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({ message: "暂停", expected_revision: 1 }),
      expect.any(Object),
    );
    expect(state.api.assessmentAttemptAction).not.toHaveBeenCalled();
    expect(state.api.controlConversationTurn).not.toHaveBeenCalled();
  });

  it("shows Maya Team assessment replies as ordinary member messages and continues through its composer", async () => {
    const mayaTeamSession = (turns: unknown[], revision: number) => ({
      entry_kind: "maya_team" as const,
      chat_visibility: "private" as const,
      origin: "published_course_team" as const,
      read_only: false,
      can_send: true,
      id: conversationId,
      team: {
        id: "77777777-7777-4777-8777-777777777777",
        version_id: "88888888-8888-4888-8888-888888888888",
        course_id: courseId,
        name: "Course Dialogue Team",
        available: true,
        members: [
          {
            id: "bowen-member",
            name: "Bowen",
            avatar_config: {},
            position: 0,
            is_leader: true,
            available: true,
          },
        ],
      },
      revision,
      turns,
      created_at: "2026-10-04T00:00:00Z",
    });
    const pausedTurn = {
      id: requestId,
      user_text: "查我的原记录",
      assistant_text: null,
      mode: "mock" as const,
      state: "ready" as const,
      safe_error_code: null,
      sources: [],
      routing: { mode: "all" as const, participant_ids: [] },
      member_results: [
        {
          id: "member-result-1",
          participant_id: "bowen-member",
          speaker_name: "Bowen",
          ordinal: 0,
          state: "ready" as const,
          assistant_text:
            "已暂停。进度：已回答 1/4 题。你的原始回答是 My original answer。",
          sources: [],
          safe_error_code: null,
        },
      ],
      assessment_result: assessmentResult("paused", "assessment.paused"),
    };
    const continuedTurn = {
      ...pausedTurn,
      id: "77777777-7777-4777-8777-777777777777",
      user_text: "继续",
      member_results: [
        {
          ...pausedTurn.member_results[0],
          id: "member-result-2",
          assistant_text:
            "已继续。进度：已回答 1/4 题。第 2 题：What did the second question ask?",
        },
      ],
      assessment_result: assessmentResult("in_progress", "assessment.resumed"),
    };
    const paused = mayaTeamSession([pausedTurn], 1);
    const continued = mayaTeamSession([pausedTurn, continuedTurn], 2);
    state.api.conversationSessions.mockResolvedValueOnce([paused]);
    state.api.conversationSession.mockResolvedValueOnce(paused);
    state.api.streamTeamConversation.mockResolvedValueOnce(continued);
    renderChat();

    fireEvent.click(
      await screen.findByRole("button", { name: "查我的原记录" }),
    );
    expect(await screen.findByText(/已暂停。进度/)).toBeTruthy();
    expect(screen.getByText(/My original answer/)).toBeTruthy();
    expect(screen.queryByText(/assessment\.paused|88888888/)).toBeNull();
    expect(
      screen.queryByRole("button", { name: /pause assessment/i }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: /resume assessment/i }),
    ).toBeNull();
    expect(screen.getByRole("textbox", { name: "Message" })).toBeTruthy();

    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "继续" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(/已继续。进度/)).toBeTruthy();
    expect(screen.getByText(/What did the second question ask/)).toBeTruthy();
    expect(state.api.streamTeamConversation).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({ message: "继续" }),
      expect.any(Object),
    );
    expect(state.api.assessmentAttemptAction).not.toHaveBeenCalled();
    expect(state.api.controlConversationTurn).not.toHaveBeenCalled();
  });
});
