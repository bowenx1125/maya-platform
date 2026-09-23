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
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    user: { courses: [{ course_id: "course", role: state.role }], groups: [] },
  }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => `/${state.role}/chat`,
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("../components/avatar", () => ({
  AvatarPreview: () => <div data-testid="avatar" />,
}));
vi.mock("../components/stage3d/scholar-scene", () => ({
  ScholarScene: () => <div data-testid="scene" />,
}));

import { AgentChat } from "../components/agent-chat";
import { AppShell } from "../components/app-shell";
import { ClassroomLive } from "../components/classroom-live";
import { DemoCompositionBadge } from "../components/demo-composition";
import { LocaleProvider } from "../components/locale";

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
  state.role = "teacher";
  state.api = {
    chatAgents: vi.fn().mockResolvedValue([agent]),
    conversations: vi.fn().mockResolvedValue([]),
    createConversation: vi.fn().mockResolvedValue(conversation),
    sendConversation: vi.fn().mockResolvedValue(completedConversation),
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
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("private Agent chat", () => {
  it("starts from the sidebar and sends consecutive messages with the latest revision", async () => {
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <AgentChat />
        </AppShell>
      </LocaleProvider>,
    );
    await screen.findByTestId("avatar");
    const nav = within(screen.getByRole("navigation"));
    expect(nav.queryByText("Back")).toBeNull();
    expect(nav.queryByText("Done")).toBeNull();
    fireEvent.click(await nav.findByRole("button", { name: "New" }));
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
    const first = await state.api.sendConversation.mock.results[0].value;
    state.api.sendConversation.mockResolvedValue({
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
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "Why?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Following the earlier reply");
    expect(screen.getByText("A considered reply")).toBeTruthy();
    expect(
      state.api.sendConversation.mock.calls.map(
        (call) => call[1].expected_revision,
      ),
    ).toEqual([0, 1]);
    expect(state.api.createConversation).toHaveBeenCalledTimes(1);
  });

  it("uses the selected Agent, renders the response, and preserves history on reentry without Refresh", async () => {
    const view = render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    await screen.findByTestId("avatar");
    expect(screen.getByRole("heading", { name: "Chats" }).className).toBe(
      "sr-only",
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("A considered reply");
    expect(state.api.createConversation).toHaveBeenCalledWith("version");
    expect(state.api.sendConversation).toHaveBeenCalledWith(
      "conversation",
      expect.objectContaining({ message: "Hello", expected_revision: 0 }),
    );
    expect(
      (screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement)
        .value,
    ).toBe("");
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
    const saved = await state.api.sendConversation.mock.results[0].value;
    state.api.conversations.mockResolvedValue([saved]);
    view.unmount();
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    await screen.findByText("A considered reply");
    expect(state.api.sendConversation).toHaveBeenCalledTimes(1);
    expect(state.api.conversations).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("button", { name: "Voice" })).toBeNull();
  });

  it("reuses an uncertain request ID instead of creating a second paid request", async () => {
    state.api.conversations.mockResolvedValue([completedConversation]);
    state.api.sendConversation.mockClear();
    state.api.sendConversation.mockRejectedValueOnce(
      new Error("Network unavailable"),
    );
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    await screen.findByTestId("avatar");
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("A considered reply");
    expect(state.api.sendConversation.mock.calls[0][1]).toEqual(
      state.api.sendConversation.mock.calls[1][1],
    );
    expect(state.api.createConversation).not.toHaveBeenCalled();
  });

  it("moves the draft into the transcript immediately and keeps the icon inside the composer", async () => {
    let resolve!: (value: unknown) => void;
    const saved = completedConversation;
    state.api.sendConversation.mockReturnValue(
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
    await act(async () => resolve(saved));
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
    state.api.sendConversation.mockClear();
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
    expect(screen.getByRole("button", { name: "Read-only" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(state.api.sendConversation).not.toHaveBeenCalled();
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
    fireEvent.change(within(dialog).getByLabelText("API Key"), {
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
        data: JSON.stringify({ ...snapshot, sequence: 3, active: false }),
      }),
    );
    expect(screen.getByText("Live offline")).toBeTruthy();
    expect(send).not.toHaveBeenCalled();
    cleanup();
    expect(close).toHaveBeenCalled();
  });
});
