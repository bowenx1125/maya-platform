import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  api: {} as Record<string, ReturnType<typeof vi.fn>>,
  role: "teacher",
  userId: "test-user",
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    user: {
      id: state.userId,
      courses: [{ course_id: "course", role: state.role }],
      groups: [],
    },
  }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => `/${state.role}/chat`,
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("../components/avatar", () => ({
  AvatarPreview: (props: { assetUrl?: string }) => (
    <div data-testid="avatar" data-asset-url={props.assetUrl} />
  ),
}));
vi.mock("../components/stage3d/scholar-scene", () => ({
  ScholarScene: () => <div data-testid="scene" />,
}));

import { AgentChat } from "../components/agent-chat";
import { AppShell } from "../components/app-shell";
import { ClassroomLive } from "../components/classroom-live";
import { DemoCompositionBadge } from "../components/demo-composition";
import { LocaleProvider } from "../components/locale";
import { abandonChatRequest, getChatRequest } from "../lib/chat-request-store";
import {
  ChatRequestPendingError,
  PlatformApi,
  PlatformApiError,
  type ChatStreamHooks,
  type ChatSession,
} from "../lib/api/platform";

const agent = {
  agent_id: "agent",
  version_id: "version",
  course_id: "course",
  name: "Socrates",
  version_label: "V1.0",
  avatar_config: {},
};
const conversation = {
  id: "conversation",
  agent,
  revision: 0,
  turns: [],
  created_at: "2026-09-22T00:00:00Z",
};
const completedConversation = {
  ...conversation,
  revision: 1,
  turns: [
    {
      id: "turn",
      user_text: "Hello",
      assistant_text: "A considered reply",
      mode: "mock",
      state: "ready",
      sources: [],
      safe_error_code: null,
    },
  ],
};
const settings = {
  revision: 0,
  credential_ready: false,
  components: [
    { key: "llm", mode: "mock", switchable: true, status: "unchecked" },
    { key: "tts", mode: "mock", switchable: false, status: "deferred" },
  ],
};

beforeEach(() => {
  abandonChatRequest();
  state.userId = `test-user-${Date.now()}-${Math.random()}`;
  state.role = "teacher";
  state.api = {
    chatAgents: vi.fn().mockResolvedValue([agent]),
    conversations: vi.fn().mockResolvedValue([]),
    createConversation: vi.fn().mockResolvedValue(conversation),
    sendConversation: vi.fn().mockResolvedValue(completedConversation),
    streamConversation: vi.fn().mockResolvedValue({
      session: completedConversation,
      audioUrl: null,
      voiceProfileId: null,
      contentType: null,
    }),
    conversation: vi.fn().mockResolvedValue(conversation),
    deleteConversation: vi.fn().mockResolvedValue(undefined),
    providerSettings: vi.fn().mockResolvedValue(settings),
    updateProviderSettings: vi
      .fn()
      .mockResolvedValue({ ...settings, revision: 1, credential_ready: true }),
    checkProvider: vi.fn().mockResolvedValue(settings),
    demoStatus: vi.fn().mockResolvedValue({
      baseline: { system_baseline: true, immutable: true, usable: true },
      composition: {
        components: [
          { key: "llm", mode: "mock" },
          { key: "tts", mode: "mock" },
        ],
      },
    }),
    classroomLive: vi.fn().mockResolvedValue({
      debate_id: "debate",
      course_id: "course",
      topic: "Public",
    }),
    liveSnapshot: vi.fn().mockResolvedValue({
      active: true,
      debate_id: "debate",
      sequence: 1,
      participants: [],
      turns: [],
      playback: null,
      server_time: "2026-09-22T00:00:00Z",
    }),
  };
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(
    () => undefined,
  );
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
});
afterEach(() => {
  cleanup();
  abandonChatRequest();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function startNewAgentChat() {
  const nav = within(screen.getByRole("navigation"));
  fireEvent.click(nav.getByRole("button", { name: "New" }));
  fireEvent.click(
    await screen.findByRole("button", { name: /New Agent chat/ }),
  );
  fireEvent.click(await screen.findByRole("button", { name: /Socrates/ }));
  return screen.findByRole("textbox", { name: "Message" });
}

describe("private Agent chat", () => {
  it("starts from the sidebar and sends consecutive messages with the latest revision", async () => {
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <AgentChat />
        </AppShell>
      </LocaleProvider>,
    );
    await screen.findByRole("combobox", { name: "Agent" });
    const nav = within(screen.getByRole("navigation"));
    expect(nav.queryByText("Back")).toBeNull();
    expect(nav.queryByText("Done")).toBeNull();
    await startNewAgentChat();
    expect(state.api.createConversation).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(
        nav.getByRole("button", { name: "New" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    expect(
      within(screen.getByRole("main")).queryByRole("button", {
        name: "New",
      }),
    ).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("A considered reply");
    const first = (await state.api.streamConversation.mock.results[0].value)
      .session;
    state.api.streamConversation.mockResolvedValue({
      session: {
        ...first,
        revision: 2,
        turns: [
          ...first.turns,
          {
            ...first.turns[0],
            id: "second",
            user_text: "Why?",
            assistant_text: "Following the earlier reply",
          },
        ],
      },
      audioUrl: null,
      voiceProfileId: null,
      contentType: null,
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "Why?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Following the earlier reply");
    expect(screen.getByText("A considered reply")).toBeTruthy();
    expect(
      state.api.streamConversation.mock.calls.map(
        (call) => call[1].expected_revision,
      ),
    ).toEqual([0, 1]);
    expect(state.api.createConversation).toHaveBeenCalledTimes(1);
  });

  it("uses the selected Agent, renders the response, and preserves history on reentry without Refresh", async () => {
    state.api.streamConversation.mockResolvedValue({
      session: completedConversation,
      audioUrl: "/api/v1/conversations/conversation/audio/legacy",
      ttsErrorCode: "tts_failed",
    });
    const view = render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    await screen.findByRole("combobox", { name: "Agent" });
    expect(document.querySelector("audio")).toBeNull();
    expect(screen.getByRole("heading", { name: "Chats" }).className).toBe(
      "sr-only",
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "我喜欢你" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("A considered reply");
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(state.api.createConversation).toHaveBeenCalledWith("version");
    expect(state.api.streamConversation).toHaveBeenCalledWith(
      "conversation",
      expect.objectContaining({
        message: "我喜欢你",
        expected_revision: 0,
      }),
      expect.objectContaining({ onTextDone: expect.any(Function) }),
    );
    expect(state.api.streamConversation.mock.calls[0][1]).not.toHaveProperty(
      "lang",
    );
    expect(
      (screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement)
        .value,
    ).toBe("");
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
    const saved = (await state.api.streamConversation.mock.results[0].value)
      .session;
    state.api.conversations.mockResolvedValue([saved]);
    view.unmount();
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    await screen.findByText("A considered reply");
    expect(state.api.streamConversation).toHaveBeenCalledTimes(1);
    expect(state.api.conversations).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("button", { name: "Voice" })).toBeNull();
  });

  it("keeps Chats focused on conversation without a 3D model panel", async () => {
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    await screen.findByRole("combobox", { name: "Agent" });
    expect(screen.queryByRole("combobox", { name: "3D model" })).toBeNull();
    expect(screen.queryByTestId("avatar")).toBeNull();
    expect(screen.getByRole("textbox", { name: "Message" })).toBeTruthy();
  });

  it("reuses an uncertain request ID instead of creating a second paid request", async () => {
    state.api.conversations.mockResolvedValue([completedConversation]);
    state.api.streamConversation.mockClear();
    state.api.streamConversation.mockRejectedValueOnce(
      new Error("Network unavailable"),
    );
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    await screen.findByRole("combobox", { name: "Agent" });
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("A considered reply");
    expect(state.api.streamConversation.mock.calls[0][1]).toEqual(
      state.api.streamConversation.mock.calls[1][1],
    );
    expect(state.api.createConversation).not.toHaveBeenCalled();
  });

  it("settles a persisted known-failed turn before accepting a new message", async () => {
    state.api.conversations.mockResolvedValue([]);
    state.api.streamConversation.mockRejectedValueOnce(
      new Error("The response was lost"),
    );
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    const input = await screen.findByRole("textbox", { name: "Message" });
    fireEvent.change(input, { target: { value: "Known failed request" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("alert");
    const requestId = getChatRequest()?.requestId;
    expect(requestId).toBeTruthy();
    cleanup();

    const failedSession = {
      ...conversation,
      revision: 1,
      turns: [
        {
          ...completedConversation.turns[0],
          id: requestId,
          user_text: "Known failed request",
          assistant_text: null,
          state: "failed",
          safe_error_code: "chat_failed",
        },
      ],
    } as unknown as ChatSession;
    state.api.conversations.mockResolvedValue([failedSession]);
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    const reopenedInput = await screen.findByRole("textbox", {
      name: "Message",
    });
    await waitFor(() => expect(getChatRequest()).toBeNull());
    expect(reopenedInput).toHaveProperty("value", "");

    fireEvent.change(reopenedInput, {
      target: { value: "A distinct follow-up" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("A considered reply");
    const request = state.api.streamConversation.mock.calls.at(-1)?.[1];
    expect(request?.request_id).not.toBe(requestId);
    expect(request?.expected_revision).toBe(1);
    expect(request?.message).toBe("A distinct follow-up");
  });

  it("refreshes after a terminal unknown outcome and sends a new message at the latest revision", async () => {
    const unknownSession = {
      ...conversation,
      revision: 1,
      turns: [
        {
          id: "unknown-turn",
          user_text: "A question with an unknown outcome",
          assistant_text: null,
          mode: "mock",
          state: "acceptance_unknown",
          sources: [],
          safe_error_code: "chat_acceptance_unknown",
        },
      ],
    };
    state.api.streamConversation.mockImplementationOnce(
      async (_id, _body, hooks) => {
        await Promise.resolve();
        hooks?.onTerminalError?.(
          unknownSession,
          new PlatformApiError(502, "chat_acceptance_unknown", {
            code: "chat_acceptance_unknown",
            message: "chat_acceptance_unknown",
          }),
        );
        throw new PlatformApiError(502, "chat_acceptance_unknown", {
          code: "chat_acceptance_unknown",
          message: "chat_acceptance_unknown",
        });
      },
    );
    state.api.streamConversation.mockResolvedValueOnce({
      session: {
        ...unknownSession,
        revision: 2,
        turns: [
          ...unknownSession.turns,
          {
            id: "new-turn",
            user_text: "A new follow-up",
            assistant_text: "A new reply",
            mode: "mock",
            state: "ready",
            sources: [],
            safe_error_code: null,
          },
        ],
      },
      audioUrl: null,
      voiceProfileId: null,
      contentType: null,
    });
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    await screen.findByRole("combobox", { name: "Agent" });
    const input = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(input, {
      target: { value: "A question with an unknown outcome" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("This request's outcome is unknown.");
    expect(input).toHaveProperty("value", "A question with an unknown outcome");
    expect(
      within(screen.getByRole("log")).getByText(
        "A question with an unknown outcome",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Send" })).toHaveProperty(
      "disabled",
      false,
    );
    fireEvent.change(input, { target: { value: "A new follow-up" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("A new reply");
    const calls = state.api.streamConversation.mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[1][1].expected_revision).toBe(1);
    expect(calls[1][1].request_id).not.toBe(calls[0][1].request_id);
  });

  it("keeps the same ID for persisted acceptance_unknown even with chat_interrupted code", async () => {
    state.api.conversations.mockResolvedValue([]);
    const requests: Array<{
      request_id: string;
      expected_revision: number;
      message: string;
    }> = [];
    state.api.streamConversation.mockImplementation(
      async (_id, body, hooks) => {
        await Promise.resolve();
        requests.push(body);
        const unknownSession = {
          ...conversation,
          revision: 1,
          turns: [
            {
              id: body.request_id,
              user_text: body.message,
              assistant_text: null,
              mode: "real",
              state: "acceptance_unknown",
              sources: [],
              safe_error_code: "chat_interrupted",
            },
          ],
        } as unknown as ChatSession;
        const interrupted = new PlatformApiError(503, "chat_interrupted", {
          code: "chat_interrupted",
          message: "chat_interrupted",
        });
        hooks?.onTerminalError?.(unknownSession, interrupted);
        throw interrupted;
      },
    );
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    const input = await screen.findByRole("textbox", { name: "Message" });
    fireEvent.change(input, {
      target: { value: "Interrupted while processing" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(getChatRequest()?.status).toBe("uncertain"));
    const firstRequestId = getChatRequest()?.requestId;
    expect(firstRequestId).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[1]).toEqual(requests[0]);
    expect(getChatRequest()?.requestId).toBe(firstRequestId);
    expect(getChatRequest()?.status).toBe("uncertain");
    expect(state.api.sendConversation).not.toHaveBeenCalled();
  });

  it("restores a saved chat_interrupted unknown turn and reuses its request ID after reload", async () => {
    const unknownSession = {
      ...completedConversation,
      revision: 1,
      turns: [
        {
          ...completedConversation.turns[0],
          id: "saved-interrupted-request",
          assistant_text: null,
          state: "acceptance_unknown",
          safe_error_code: "chat_interrupted",
        },
      ],
    } as unknown as ChatSession;
    state.api.conversations.mockResolvedValue([unknownSession]);
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );

    const input = await screen.findByRole("textbox", { name: "Message" });
    await waitFor(() => expect(input).toHaveProperty("value", "Hello"));
    expect(getChatRequest()?.requestId).toBe("saved-interrupted-request");
    expect(getChatRequest()?.status).toBe("uncertain");
    expect(screen.getByRole("alert").textContent).toContain(
      "This request's outcome is unknown.",
    );
    expect(state.api.streamConversation).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("A considered reply");
    expect(state.api.streamConversation).toHaveBeenCalledTimes(1);
    expect(state.api.streamConversation.mock.calls[0][1]).toEqual({
      request_id: "saved-interrupted-request",
      message: "Hello",
      expected_revision: 0,
    });
  });

  it("ignores an old ready callback after retrying the same request ID", async () => {
    let firstHooks!: ChatStreamHooks;
    let retryHooks!: ChatStreamHooks;
    let finishRetry!: (value: {
      session: ChatSession;
      audioUrl: null;
      voiceProfileId: null;
      contentType: null;
      ttsErrorCode: null;
    }) => void;
    state.api.streamConversation.mockImplementationOnce((_id, _body, hooks) => {
      firstHooks = hooks;
      return Promise.reject(new Error("The first response was lost"));
    });
    state.api.streamConversation.mockImplementationOnce((_id, _body, hooks) => {
      retryHooks = hooks;
      return new Promise((resolve) => {
        finishRetry = resolve;
      });
    });
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    const input = await screen.findByRole("textbox", { name: "Message" });
    fireEvent.change(input, { target: { value: "Retry the same request" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("alert");
    const original = getChatRequest();
    expect(original?.status).toBe("uncertain");
    expect(original?.requestId).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(state.api.streamConversation).toHaveBeenCalledTimes(2),
    );
    const retry = getChatRequest();
    expect(retry?.status).toBe("in_flight");
    expect(retry?.requestId).toBe(original?.requestId);
    expect(retry?.attemptId).not.toBe(original?.attemptId);
    expect(state.api.streamConversation.mock.calls[1][1]).toEqual(
      state.api.streamConversation.mock.calls[0][1],
    );

    const oldReady = {
      ...completedConversation,
      turns: [
        {
          ...completedConversation.turns[0],
          id: original!.requestId,
          user_text: "Retry the same request",
        },
      ],
    } as unknown as ChatSession;
    await act(async () =>
      firstHooks.onTerminalError?.(
        oldReady,
        new PlatformApiError(503, "chat_acceptance_unknown", {
          code: "chat_acceptance_unknown",
          message: "chat_acceptance_unknown",
        }),
      ),
    );
    expect(getChatRequest()?.attemptId).toBe(retry?.attemptId);
    expect(getChatRequest()?.status).toBe("in_flight");
    expect(screen.getByRole("button", { name: "Send" })).toHaveProperty(
      "disabled",
      true,
    );

    await act(async () =>
      finishRetry({
        session: oldReady,
        audioUrl: null,
        voiceProfileId: null,
        contentType: null,
        ttsErrorCode: null,
      }),
    );
    expect(retryHooks).toBeDefined();
    await screen.findByText("A considered reply");
    expect(getChatRequest()).toBeNull();
  });

  it("keeps the uncertain request ID while a replay is pending and observes it to ready", async () => {
    state.api.streamConversation.mockRejectedValueOnce(
      new Error("The stream disconnected"),
    );
    let pendingSession: ChatSession = conversation as unknown as ChatSession;
    let readySession: ChatSession = conversation as unknown as ChatSession;
    state.api.conversation
      .mockImplementationOnce(async () => pendingSession)
      .mockImplementationOnce(async () => readySession);
    state.api.streamConversation.mockImplementationOnce(
      async (_id, body, hooks) => {
        await Promise.resolve();
        pendingSession = {
          ...conversation,
          revision: 1,
          turns: [
            {
              id: body.request_id,
              user_text: body.message,
              assistant_text: null,
              mode: "mock",
              state: "pending",
              sources: [],
              safe_error_code: null,
            },
          ],
        } as unknown as ChatSession;
        readySession = {
          ...pendingSession,
          turns: pendingSession.turns.map((turn) => ({
            ...turn,
            assistant_text: "Finished after pending",
            state: "ready",
          })),
        } as unknown as ChatSession;
        hooks?.onPending?.(pendingSession, body.request_id);
        throw new ChatRequestPendingError();
      },
    );
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    const input = await screen.findByRole("textbox", { name: "Message" });
    fireEvent.change(input, { target: { value: "Still generating" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(state.api.streamConversation).toHaveBeenCalledTimes(2),
    );
    await waitFor(
      () => expect(screen.getByText("Finished after pending")).toBeTruthy(),
      { timeout: 4000 },
    );
    const requests = state.api.streamConversation.mock.calls.map(
      (call) => call[1],
    );
    expect(requests[1]).toEqual(requests[0]);
    expect(state.api.streamConversation).toHaveBeenCalledTimes(2);
  });

  it("adopts a persisted pending turn after reload and observes it without replaying POST", async () => {
    const pendingSession = {
      ...conversation,
      revision: 1,
      turns: [
        {
          id: "persisted-request",
          user_text: "Continue observing this request",
          assistant_text: null,
          mode: "real",
          state: "pending",
          sources: [],
          safe_error_code: null,
        },
      ],
    } as unknown as ChatSession;
    const readySession = {
      ...pendingSession,
      turns: pendingSession.turns.map((turn) => ({
        ...turn,
        assistant_text: "Recovered after reload",
        state: "ready",
      })),
    } as unknown as ChatSession;
    state.api.conversations.mockResolvedValue([pendingSession]);
    state.api.conversation
      .mockResolvedValueOnce(pendingSession)
      .mockResolvedValueOnce(readySession);

    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );

    await screen.findByRole("status");
    await waitFor(() => expect(getChatRequest()?.status).toBe("observing"));
    expect(getChatRequest()?.requestId).toBe("persisted-request");
    await screen.findByText("Recovered after reload", {}, { timeout: 4000 });
    expect(state.api.streamConversation).not.toHaveBeenCalled();
    expect(state.api.conversation).toHaveBeenCalledTimes(2);
  });

  it("refreshes cached history on explicit reopen and observes newly persisted pending work via GET", async () => {
    const pendingSession = {
      ...completedConversation,
      revision: 2,
      turns: [
        ...completedConversation.turns,
        {
          ...completedConversation.turns[0],
          id: "remote-pending-request",
          user_text: "Another client is still working",
          assistant_text: null,
          state: "pending",
        },
      ],
    } as unknown as ChatSession;
    const readySession = {
      ...pendingSession,
      turns: pendingSession.turns.map((turn) =>
        turn.id === "remote-pending-request"
          ? {
              ...turn,
              assistant_text: "Finished after reopen",
              state: "ready",
            }
          : turn,
      ),
    } as unknown as ChatSession;
    state.api.conversations.mockResolvedValue([completedConversation]);
    state.api.conversation
      .mockResolvedValueOnce(pendingSession)
      .mockResolvedValueOnce(readySession);
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <AgentChat />
        </AppShell>
      </LocaleProvider>,
    );
    await screen.findByText("A considered reply");
    await startNewAgentChat();
    fireEvent.click(screen.getByRole("button", { name: "Hello" }));
    await screen.findByText("Finished after reopen", {}, { timeout: 4000 });
    expect(state.api.conversation).toHaveBeenCalledTimes(2);
    expect(state.api.streamConversation).not.toHaveBeenCalled();
    expect(state.api.sendConversation).not.toHaveBeenCalled();
    expect(getChatRequest()).toBeNull();
  });

  it("preserves the current unknown request when history refresh fails, then retries GET without POST", async () => {
    const otherConversation = {
      ...completedConversation,
      id: "other-conversation",
      turns: [
        {
          ...completedConversation.turns[0],
          id: "other-turn",
          user_text: "Other chat",
          assistant_text: "Other answer",
        },
      ],
    };
    state.api.conversations.mockResolvedValue([
      completedConversation,
      otherConversation,
    ]);
    state.api.streamConversation.mockRejectedValueOnce(
      new Error("The response was lost"),
    );
    state.api.conversation
      .mockRejectedValueOnce(new Error("History refresh unavailable"))
      .mockResolvedValueOnce(otherConversation);
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    const input = await screen.findByRole("textbox", { name: "Message" });
    fireEvent.change(input, { target: { value: "Keep this unknown request" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("alert");
    const requestId = getChatRequest()?.requestId;
    expect(requestId).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Other chat" }));
    const refreshError = await screen.findByRole("alert");
    expect(refreshError.textContent).toContain(
      "Retry the refresh before sending here.",
    );
    expect(input).toHaveProperty("value", "Keep this unknown request");
    expect(getChatRequest()?.requestId).toBe(requestId);
    expect(state.api.streamConversation).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Send" })).toHaveProperty(
      "disabled",
      true,
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("Other answer");
    expect(input).toHaveProperty("value", "");
    expect(getChatRequest()).toBeNull();
    expect(state.api.conversation).toHaveBeenCalledTimes(2);
    expect(state.api.streamConversation).toHaveBeenCalledTimes(1);
  });

  it("preserves a new draft and selection when an old stream closes after text_done", async () => {
    const otherConversation = {
      ...completedConversation,
      id: "other-conversation",
      turns: [
        {
          ...completedConversation.turns[0],
          id: "other-turn",
          user_text: "Other chat",
          assistant_text: "Other answer",
        },
      ],
    };
    state.api.conversations.mockResolvedValue([
      completedConversation,
      otherConversation,
    ]);
    state.api.conversation.mockResolvedValue(otherConversation);
    let finish!: (result: unknown) => void;
    let onTextDone!: (session: typeof completedConversation) => void;
    let onUncertain!: (
      session: ChatSession | null,
      error: PlatformApiError,
    ) => void;
    state.api.streamConversation.mockImplementationOnce((_id, _body, hooks) => {
      onTextDone = hooks.onTextDone;
      onUncertain = hooks.onUncertain;
      return new Promise((resolve) => {
        finish = resolve;
      });
    });
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    const input = await screen.findByRole("textbox", { name: "Message" });
    fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(state.api.streamConversation).toHaveBeenCalledTimes(1),
    );
    await act(async () => onTextDone(completedConversation));
    expect(getChatRequest()).toBeNull();
    expect(screen.getByRole("button", { name: "Other chat" })).toHaveProperty(
      "disabled",
      false,
    );
    fireEvent.click(screen.getByRole("button", { name: "Other chat" }));
    await waitFor(() =>
      expect(state.api.conversation).toHaveBeenCalledWith("other-conversation"),
    );
    fireEvent.change(input, {
      target: { value: "My next draft must survive" },
    });
    await act(async () =>
      onUncertain(
        completedConversation as unknown as ChatSession,
        new PlatformApiError(503, "chat_transport_uncertain", {
          code: "chat_transport_uncertain",
          message: "chat_transport_uncertain",
        }),
      ),
    );
    await act(async () =>
      finish({
        session: completedConversation,
        audioUrl: null,
        voiceProfileId: null,
        contentType: null,
        ttsErrorCode: null,
      }),
    );
    expect(input).toHaveProperty("value", "My next draft must survive");
    expect(
      within(screen.getByRole("log")).getByText("Other answer"),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("log")).queryByText("A considered reply"),
    ).toBeNull();
  });

  it.each(["onUncertain", "onPending", "onTerminalError"] as const)(
    "ignores a late %s callback after New while preserving the new draft",
    async (callback) => {
      let hooks!: ChatStreamHooks;
      let finish!: (value: {
        session: ChatSession;
        audioUrl: null;
        voiceProfileId: null;
        contentType: null;
        ttsErrorCode: null;
      }) => void;
      let oldRequestId = "";
      const oldReady = {
        ...conversation,
        revision: 1,
        turns: [
          {
            ...completedConversation.turns[0],
            id: "old-request",
            user_text: "Old sent message",
            assistant_text: "Old settled reply",
          },
        ],
      } as unknown as ChatSession;
      state.api.streamConversation.mockImplementationOnce(
        (_id, body, captured) => {
          oldRequestId = body.request_id;
          hooks = captured;
          return new Promise((resolve) => {
            finish = resolve;
          });
        },
      );
      render(
        <LocaleProvider initialLocale="en">
          <AppShell role="teacher">
            <AgentChat />
          </AppShell>
        </LocaleProvider>,
      );
      const input = await screen.findByRole("textbox", { name: "Message" });
      fireEvent.change(input, { target: { value: "Old sent message" } });
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
      await waitFor(() =>
        expect(state.api.streamConversation).toHaveBeenCalledTimes(1),
      );
      await act(async () => hooks.onTextDone?.(oldReady));
      await screen.findByText("Old settled reply");
      const newInput = await startNewAgentChat();
      expect(
        within(screen.getByRole("log")).queryByText("Old settled reply"),
      ).toBeNull();
      fireEvent.change(newInput, { target: { value: "My new-chat draft" } });
      await act(async () => {
        const failure = new PlatformApiError(503, "chat_transport_uncertain", {
          code: "chat_transport_uncertain",
          message: "chat_transport_uncertain",
        });
        if (callback === "onPending") {
          hooks.onPending?.(oldReady, oldRequestId);
        } else if (callback === "onTerminalError") {
          hooks.onTerminalError?.(oldReady, failure);
        } else {
          hooks.onUncertain?.(oldReady, failure);
        }
      });
      await act(async () =>
        finish({
          session: oldReady,
          audioUrl: null,
          voiceProfileId: null,
          contentType: null,
          ttsErrorCode: null,
        }),
      );
      expect(newInput).toHaveProperty("value", "My new-chat draft");
      expect(getChatRequest()).toBeNull();
      expect(
        within(screen.getByRole("log")).queryByText("Old settled reply"),
      ).toBeNull();
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.getByRole("button", { name: "Send" })).toHaveProperty(
        "disabled",
        false,
      );
    },
  );

  it.each(["onUncertain", "onPending", "onTerminalError"] as const)(
    "preserves a newer request when an old %s callback and finally arrive",
    async (callback) => {
      let oldHooks!: ChatStreamHooks;
      let finishOld!: (value: {
        session: ChatSession;
        audioUrl: null;
        voiceProfileId: null;
        contentType: null;
        ttsErrorCode: null;
      }) => void;
      state.api.streamConversation
        .mockImplementationOnce((_id, _body, hooks) => {
          oldHooks = hooks;
          return new Promise((resolve) => {
            finishOld = resolve;
          });
        })
        .mockImplementationOnce(() => new Promise(() => undefined));
      render(
        <LocaleProvider initialLocale="en">
          <AgentChat />
        </LocaleProvider>,
      );
      const input = await screen.findByRole("textbox", { name: "Message" });
      fireEvent.change(input, { target: { value: "Old message" } });
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
      await waitFor(() =>
        expect(state.api.streamConversation).toHaveBeenCalledTimes(1),
      );
      await act(async () =>
        oldHooks.onTextDone?.(completedConversation as unknown as ChatSession),
      );
      fireEvent.change(input, { target: { value: "New active message" } });
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
      await waitFor(() =>
        expect(state.api.streamConversation).toHaveBeenCalledTimes(2),
      );
      const newRequestId = getChatRequest()?.requestId;
      expect(newRequestId).toBeTruthy();
      await act(async () => {
        const failure = new PlatformApiError(503, "chat_transport_uncertain", {
          code: "chat_transport_uncertain",
          message: "chat_transport_uncertain",
        });
        if (callback === "onPending") {
          oldHooks.onPending?.(
            completedConversation as unknown as ChatSession,
            "turn",
          );
        } else if (callback === "onTerminalError") {
          oldHooks.onTerminalError?.(
            completedConversation as unknown as ChatSession,
            failure,
          );
        } else {
          oldHooks.onUncertain?.(
            completedConversation as unknown as ChatSession,
            failure,
          );
        }
        finishOld({
          session: completedConversation as unknown as ChatSession,
          audioUrl: null,
          voiceProfileId: null,
          contentType: null,
          ttsErrorCode: null,
        });
      });
      expect(getChatRequest()?.requestId).toBe(newRequestId);
      expect(getChatRequest()?.status).toBe("in_flight");
      expect(screen.getByRole("button", { name: "Send" })).toHaveProperty(
        "disabled",
        true,
      );
      expect(screen.queryByRole("alert")).toBeNull();
    },
  );

  it("recovers a saved HTTP 502 response without restoring or resending its text", async () => {
    state.api.conversations.mockResolvedValue([]);
    const api = new PlatformApi({
      baseUrl: "http://maya.test/api/v1",
      csrfToken: "csrf-token-csrf-token-csrf-token",
    });
    state.api.streamConversation = vi.fn(api.streamConversation.bind(api));
    let saved: ChatSession = conversation as unknown as ChatSession;
    const requests: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/messages:stream")) {
          const body = JSON.parse(init?.body as string) as Record<
            string,
            unknown
          >;
          requests.push(body);
          if (requests.length === 1) {
            saved = {
              ...conversation,
              revision: 1,
              turns: [
                {
                  id: String(body.request_id),
                  user_text: String(body.message),
                  assistant_text: "Saved despite proxy 502",
                  mode: "mock",
                  state: "ready",
                  sources: [],
                  safe_error_code: null,
                },
              ],
            } as unknown as ChatSession;
            return new Response("Proxy lost after server commit", {
              status: 502,
            });
          }
          saved = {
            ...saved,
            revision: 2,
            turns: [
              ...saved.turns,
              {
                ...saved.turns[0],
                id: String(body.request_id),
                user_text: String(body.message),
                assistant_text: "A distinct later reply",
              },
            ],
          } as unknown as ChatSession;
          return new Response(
            `event: text_done\ndata: ${JSON.stringify({ request_id: body.request_id })}\n\n`,
            { status: 200, headers: { "Content-Type": "text/event-stream" } },
          );
        }
        return new Response(JSON.stringify(saved), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    const input = await screen.findByRole("textbox", { name: "Message" });
    fireEvent.change(input, { target: { value: "Retry after proxy loss" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Saved despite proxy 502");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(input).toHaveProperty("value", "");
    expect(requests).toHaveLength(1);

    fireEvent.change(input, { target: { value: "A distinct follow-up" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("A distinct later reply");
    expect(requests).toHaveLength(2);
    expect(requests[1].request_id).not.toBe(requests[0].request_id);
    expect(requests[1].expected_revision).toBe(1);
    expect(requests[1].message).toBe("A distinct follow-up");
  });

  it("moves the draft into the transcript immediately and keeps the icon inside the composer", async () => {
    let resolve!: (value: unknown) => void;
    const saved = completedConversation;
    state.api.streamConversation.mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    const input = await screen.findByRole("textbox", { name: "Message" });
    expect(screen.queryByText("Message")).toBeNull();
    fireEvent.change(input, { target: { value: "Hello" } });
    const button = screen.getByRole("button", { name: "Send" });
    expect(button.closest("form")).toBe(input.closest("form"));
    expect(button.textContent).toBe("");
    expect(button.querySelector("svg")).not.toBeNull();
    fireEvent.click(button);
    expect(input).toHaveProperty("value", "");
    expect(within(screen.getByRole("log")).getByText("Hello")).toBeTruthy();
    expect(button).toHaveProperty("disabled", true);
    await act(async () =>
      resolve({
        session: saved,
        audioUrl: null,
        voiceProfileId: null,
        contentType: null,
      }),
    );
    expect(within(screen.getByRole("log")).getAllByText("Hello")).toHaveLength(
      1,
    );
    expect(screen.getByText("A considered reply")).toBeTruthy();
  });

  it("keeps deleted Agent history readable without allowing a new message", async () => {
    const saved = completedConversation;
    state.api.conversations.mockResolvedValue([
      { ...saved, agent: { ...agent, available: false } },
    ]);
    state.api.chatAgents.mockResolvedValue([]);
    state.api.streamConversation.mockClear();
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    await screen.findByText("A considered reply");
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(
      screen.getByRole("button", {
        name: "Read-only",
      }),
    ).toHaveProperty("disabled", true);
    expect(
      screen
        .getByRole("button", { name: "Read-only" })
        .getAttribute("aria-describedby"),
    ).toBe("chat-readonly-help");
    expect(
      screen
        .getByRole("textbox", { name: "Message" })
        .getAttribute("aria-describedby"),
    ).toBe("chat-readonly-help");
    expect(
      screen.getByText("This Agent is unavailable for new messages.")
        .textContent,
    ).toBe("This Agent is unavailable for new messages.");
    expect(state.api.streamConversation).not.toHaveBeenCalled();
  });
});

describe("provider controls", () => {
  it("opens the credential dialog without enabling Real, and Check skips Ready components", async () => {
    render(
      <LocaleProvider initialLocale="en">
        <DemoCompositionBadge />
      </LocaleProvider>,
    );
    const select = await screen.findByRole("combobox", {
      name: "Debate LLM mode",
    });
    fireEvent.change(select, { target: { value: "real" } });
    const dialog = await screen.findByRole("dialog");
    expect(state.api.updateProviderSettings).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText("DashScope API Key"), {
      target: { value: "test-only-key" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(state.api.updateProviderSettings).toHaveBeenCalledWith("course", {
        expected_revision: 0,
        component: "llm",
        mode: "real",
        api_key: "test-only-key",
      }),
    );
    state.api.providerSettings.mockResolvedValue({
      ...settings,
      components: settings.components.map((item) =>
        item.switchable ? { ...item, status: "ready" } : item,
      ),
    });
    expect(screen.getAllByRole("button", { name: "Check" })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    await waitFor(() =>
      expect(state.api.providerSettings).toHaveBeenCalledTimes(2),
    );
    expect(state.api.checkProvider).not.toHaveBeenCalled();
    expect(
      (screen.getByRole("combobox", { name: "TTS mode" }) as HTMLSelectElement)
        .disabled,
    ).toBe(true);
  });

  it("saves a teacher DashScope key without switching modes or checking providers", async () => {
    render(
      <LocaleProvider initialLocale="en">
        <DemoCompositionBadge />
      </LocaleProvider>,
    );
    await screen.findByRole("combobox", { name: "Debate LLM mode" });
    fireEvent.click(screen.getByRole("button", { name: "Set API Key" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("DashScope API Key"), {
      target: { value: "teacher-owned-test-key" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(state.api.updateProviderSettings).toHaveBeenCalledWith("course", {
        expected_revision: 0,
        component: null,
        mode: null,
        api_key: "teacher-owned-test-key",
      }),
    );
    expect(state.api.checkProvider).not.toHaveBeenCalled();
  });

  it("checks only unchecked or changed components and leaves Ready and deferred ones alone", async () => {
    let current = {
      ...settings,
      components: [
        { key: "llm", mode: "mock", switchable: true, status: "ready" },
        {
          key: "embedding",
          mode: "mock",
          switchable: true,
          status: "unchecked",
        },
        { key: "report", mode: "mock", switchable: true, status: "failed" },
        { key: "tts", mode: "mock", switchable: false, status: "deferred" },
      ],
    };
    state.api.providerSettings.mockResolvedValue(current);
    state.api.checkProvider.mockImplementation(async (_course, key) => {
      current = {
        ...current,
        components: current.components.map((item) =>
          item.key === key ? { ...item, status: "ready" } : item,
        ),
      };
      return current;
    });
    render(
      <LocaleProvider initialLocale="en">
        <DemoCompositionBadge />
      </LocaleProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Check" }));
    await waitFor(() =>
      expect(state.api.checkProvider).toHaveBeenCalledTimes(2),
    );
    expect(state.api.checkProvider.mock.calls.map((call) => call[1])).toEqual([
      "embedding",
      "report",
    ]);
  });
});

describe("student Live", () => {
  it("shares the full public transcript through a read-only socket without Refresh or controller commands", async () => {
    const snapshot = {
      active: true,
      interaction_url: "/classroom/shared-qr-token",
      debate_id: "debate",
      sequence: 1,
      participants: [{ id: "speaker", name: "Socrates", avatar_config: {} }],
      turns: [
        { id: "first", participant_id: "speaker", speech: "Opening argument" },
      ],
      playback: null,
      server_time: "2026-09-22T00:00:00Z",
    };
    state.api.liveSnapshot.mockResolvedValue(snapshot);
    const send = vi.fn();
    const close = vi.fn();
    const sockets: { onmessage?: (event: { data: string }) => void }[] = [];
    class Socket {
      send = send;
      close = close;
      constructor(public url: string) {
        sockets.push(this);
      }
      onmessage?: (event: { data: string }) => void;
    }
    vi.stubGlobal("WebSocket", Socket);
    render(
      <LocaleProvider initialLocale="en">
        <ClassroomLive />
      </LocaleProvider>,
    );
    await screen.findByTestId("scene");
    expect(
      screen.getByRole("link", { name: "Interact" }).getAttribute("href"),
    ).toBe("/classroom/shared-qr-token");
    expect(send).not.toHaveBeenCalled();
    expect(sockets).toHaveLength(1);
    expect((sockets[0] as Socket).url).toContain("/api/v1/live/debate/events");
    expect(screen.queryByRole("button", { name: "Next" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Public Debate" })).toBeTruthy();
    expect(screen.getByText("Opening argument")).toBeTruthy();
    act(() =>
      sockets[0].onmessage?.({
        data: JSON.stringify({
          ...snapshot,
          sequence: 2,
          turns: [
            ...snapshot.turns,
            {
              id: "second",
              participant_id: "speaker",
              speech: "Second argument",
            },
          ],
        }),
      }),
    );
    expect(screen.getByText("Opening argument")).toBeTruthy();
    expect(screen.getByText("Second argument")).toBeTruthy();
    act(() => sockets[0].onmessage?.({ data: JSON.stringify(snapshot) }));
    expect(screen.getByText("Second argument")).toBeTruthy();
    act(() =>
      sockets[0].onmessage?.({
        data: JSON.stringify({
          ...snapshot,
          sequence: 3,
          interaction_url: null,
        }),
      }),
    );
    expect(screen.queryByRole("link", { name: "Interact" })).toBeNull();
    expect(screen.getByRole("button", { name: "Interact" })).toHaveProperty(
      "disabled",
      true,
    );
    act(() =>
      sockets[0].onmessage?.({
        data: JSON.stringify({ ...snapshot, sequence: 4, active: false }),
      }),
    );
    expect(screen.getByText("Live offline")).toBeTruthy();
    expect(send).not.toHaveBeenCalled();
    cleanup();
    expect(close).toHaveBeenCalled();
  });
});
