import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const routerPush = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  usePathname: () => "/teacher/chat",
  useSearchParams: () => new URLSearchParams(window.location.search),
  useRouter: () => ({ push: routerPush, replace: vi.fn() }),
}));

import { AgentChat } from "../components/agent-chat";
import { LocaleProvider } from "../components/locale";
import { SessionProvider, useSession } from "../components/session-provider";
import type { AuthSession, ChatSession, PlatformApi } from "../lib/api";
import {
  getChatRequest,
  getSettledChatSession,
  resetChatRequestIdentity,
} from "../lib/chat-request-store";
import { SidebarActions } from "./sidebar-actions";

const agent = {
  agent_id: "synthetic-agent",
  version_id: "synthetic-version",
  course_id: "same-synthetic-course",
  name: "Synthetic Agent",
  version_label: "V1",
  avatar_config: {},
};
const emptyConversation = {
  id: "synthetic-A-conversation",
  agent,
  revision: 0,
  turns: [],
  created_at: "2026-09-27T00:00:00Z",
} as unknown as ChatSession;
const privateReadySession = {
  ...emptyConversation,
  revision: 1,
  turns: [
    {
      id: "synthetic-A-request",
      user_text: "Synthetic A private question",
      assistant_text: "Synthetic A private answer",
      mode: "mock",
      state: "ready",
      sources: [],
      safe_error_code: null,
    },
  ],
} as unknown as ChatSession;
function auth(
  userId: string,
  courses = [
    { course_id: agent.course_id, role: "teacher", name: "Synthetic" },
  ],
): AuthSession {
  return {
    csrf_token: `synthetic-csrf-${userId}`,
    user: {
      id: userId,
      username: userId,
      display_name: userId,
      courses,
      groups: [],
    },
  } as unknown as AuthSession;
}

function Harness() {
  const session = useSession();
  const [showChats, setShowChats] = useState(true);
  return (
    <>
      <div data-testid="actor">{session.user?.id ?? "anonymous"}</div>
      <button onClick={() => setShowChats(false)}>Leave Chats</button>
      <button onClick={() => setShowChats(true)}>Enter Chats</button>
      <button onClick={() => void session.refresh()}>Refresh identity</button>
      <button onClick={() => void session.logout()}>Public logout</button>
      <button onClick={() => void session.login("B", "synthetic")}>
        Public login B
      </button>
      <button
        onClick={() => void session.switchIdentity("B").catch(() => undefined)}
      >
        Public switch B
      </button>
      <button
        onClick={() => void session.switchIdentity("A").catch(() => undefined)}
      >
        Public switch A
      </button>
      {showChats && session.status === "authenticated" ? (
        <SidebarActions>
          <AgentChat />
        </SidebarActions>
      ) : null}
    </>
  );
}

let actor: string | null;
let api: Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  resetChatRequestIdentity();
  window.history.replaceState(null, "", "/teacher/chat");
  actor = "A";
  api = {
    me: vi.fn(async () => auth(actor ?? "A")),
    getCsrfToken: vi.fn(),
    setCsrfToken: vi.fn(),
    logout: vi.fn(async () => {
      actor = null;
    }),
    login: vi.fn(async () => {
      actor = "B";
      return auth("B");
    }),
    switchDemoIdentity: vi.fn(async (userId: string) => {
      actor = userId;
      return auth(userId);
    }),
    chatAgents: vi.fn(async () => [agent]),
    conversations: vi.fn(async () =>
      actor === "A" ? [privateReadySession] : [],
    ),
    createConversation: vi.fn(async () => emptyConversation),
    conversation: vi.fn(async () => emptyConversation),
    streamConversation: vi.fn(),
    deleteConversation: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  resetChatRequestIdentity();
  vi.restoreAllMocks();
});

function mount() {
  render(
    <LocaleProvider initialLocale="en">
      <SessionProvider api={api as unknown as PlatformApi}>
        <Harness />
      </SessionProvider>
    </LocaleProvider>,
  );
}

function openNewChatUrl() {
  window.history.replaceState(null, "", "/teacher/chat?mode=new");
}

async function pickAgentAndDone() {
  fireEvent.click(
    await screen.findByRole("button", { name: /Synthetic Agent/ }),
  );
  const done = within(screen.getByRole("navigation")).getByRole("button", {
    name: "Done",
  });
  await waitFor(() => expect(done.hasAttribute("disabled")).toBe(false));
  fireEvent.click(done);
}

async function chooseAgent() {
  await pickAgentAndDone();
  return screen.findByRole("textbox", { name: "Message" });
}

async function sendAndLeave(message: string) {
  const input = await screen.findByRole("textbox", { name: "Message" });
  fireEvent.change(input, { target: { value: message } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(api.streamConversation).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Leave Chats" }));
}

describe("Chat data follows the accepted account and course scope", () => {
  it("drops A's background settled answer before B reopens Chat in the same course", async () => {
    let finish!: (value: {
      session: ChatSession;
      audioUrl: null;
      voiceProfileId: null;
      contentType: null;
      ttsErrorCode: null;
    }) => void;
    api.streamConversation.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    mount();
    await waitFor(() =>
      expect(screen.getByTestId("actor").textContent).toBe("A"),
    );
    await sendAndLeave("Synthetic A private draft");
    await act(async () =>
      finish({
        session: privateReadySession,
        audioUrl: null,
        voiceProfileId: null,
        contentType: null,
        ttsErrorCode: null,
      }),
    );
    await waitFor(() =>
      expect(getSettledChatSession()?.id).toBe(emptyConversation.id),
    );

    fireEvent.click(screen.getByRole("button", { name: "Public switch B" }));
    await waitFor(() =>
      expect(screen.getByTestId("actor").textContent).toBe("B"),
    );
    expect(getSettledChatSession()).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Enter Chats" }));
    await screen.findByText("No chats yet.");
    expect(screen.queryByText("Synthetic A private answer")).toBeNull();
  });

  it("clears A's uncertain draft and request on logout before B logs in", async () => {
    let reject!: (error: Error) => void;
    api.streamConversation.mockImplementationOnce(
      () =>
        new Promise((_resolve, fail) => {
          reject = fail;
        }),
    );
    mount();
    await waitFor(() =>
      expect(screen.getByTestId("actor").textContent).toBe("A"),
    );
    await sendAndLeave("Synthetic A private draft");
    await act(async () => reject(new Error("synthetic transport closed")));
    await waitFor(() => expect(getChatRequest()?.status).toBe("uncertain"));

    fireEvent.click(screen.getByRole("button", { name: "Public logout" }));
    await waitFor(() =>
      expect(screen.getByTestId("actor").textContent).toBe("anonymous"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Public login B" }));
    await waitFor(() =>
      expect(screen.getByTestId("actor").textContent).toBe("B"),
    );
    expect(getChatRequest()).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Enter Chats" }));
    await screen.findByText("No chats yet.");
    expect(screen.queryByDisplayValue("Synthetic A private draft")).toBeNull();
    expect(getChatRequest()).toBeNull();
  });

  it("reloads history and hides A's local answer when B replaces A in place", async () => {
    mount();
    await screen.findByText("Synthetic A private answer");
    expect(api.conversations).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Public switch B" }));
    await waitFor(() =>
      expect(screen.getByTestId("actor").textContent).toBe("B"),
    );
    await waitFor(() => expect(api.conversations).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Synthetic A private answer")).toBeNull();
  });

  it("preserves the same actor's pending request across navigation and /me refresh", async () => {
    api.conversations.mockResolvedValue([emptyConversation]);
    api.streamConversation.mockImplementationOnce(
      () => new Promise(() => undefined),
    );
    openNewChatUrl();
    mount();
    await waitFor(() =>
      expect(screen.getByTestId("actor").textContent).toBe("A"),
    );
    await chooseAgent();
    await sendAndLeave("A request remains in flight");
    window.history.replaceState(null, "", "/teacher/chat");
    const requestId = getChatRequest()?.requestId;
    expect(requestId).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Refresh identity" }));
    await waitFor(() => expect(api.me).toHaveBeenCalledTimes(2));
    expect(getChatRequest()?.requestId).toBe(requestId);
    fireEvent.click(screen.getByRole("button", { name: "Enter Chats" }));
    await screen.findByRole("textbox", { name: "Message" });
    expect(getChatRequest()?.requestId).toBe(requestId);
    expect(screen.getByRole("status").textContent).toContain("Loading");
  });

  it("reopening the same actor's saved pending turn observes it without another POST", async () => {
    api.streamConversation.mockImplementationOnce(
      () => new Promise(() => undefined),
    );
    mount();
    await waitFor(() =>
      expect(screen.getByTestId("actor").textContent).toBe("A"),
    );
    await sendAndLeave("Observe the saved request");
    const requestId = getChatRequest()?.requestId;
    expect(requestId).toBeTruthy();
    const pendingSession = {
      ...emptyConversation,
      revision: 1,
      turns: [
        {
          id: requestId,
          user_text: "Observe the saved request",
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
        assistant_text: "Recovered after reopen",
        state: "ready",
      })),
    } as unknown as ChatSession;
    api.conversations.mockResolvedValue([pendingSession]);
    api.conversation.mockResolvedValueOnce(readySession);

    fireEvent.click(screen.getByRole("button", { name: "Enter Chats" }));
    await screen.findByText("Recovered after reopen");
    expect(getChatRequest()).toBeNull();
    expect(api.conversation).toHaveBeenCalledTimes(1);
    expect(api.streamConversation).toHaveBeenCalledTimes(1);
  });

  it("clears current and settled Chat state when the accepted course scope changes", async () => {
    const courseX = {
      course_id: agent.course_id,
      role: "teacher",
      name: "Synthetic X",
    };
    const courseY = {
      course_id: "synthetic-other-course",
      role: "teacher",
      name: "Synthetic Y",
    };
    api.me
      .mockResolvedValueOnce(auth("A", [courseX, courseY]))
      .mockResolvedValueOnce(auth("A", [courseY, courseX]));
    api.streamConversation.mockImplementationOnce(
      () => new Promise(() => undefined),
    );
    mount();
    await waitFor(() =>
      expect(screen.getByTestId("actor").textContent).toBe("A"),
    );
    await sendAndLeave("Only keep this in course X");
    const requestId = getChatRequest()?.requestId;
    expect(requestId).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Enter Chats" }));
    await screen.findByRole("textbox", { name: "Message" });
    fireEvent.click(screen.getByRole("button", { name: "Refresh identity" }));
    await waitFor(() => expect(api.me).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(api.conversations).toHaveBeenCalledTimes(3));
    expect(getChatRequest()).toBeNull();
    expect(getSettledChatSession()).toBeNull();
    expect(screen.queryByText("Only keep this in course X")).toBeNull();
  });

  it("keeps A's pending request when an identity switch is rejected", async () => {
    api.streamConversation.mockImplementationOnce(
      () => new Promise(() => undefined),
    );
    api.switchDemoIdentity.mockRejectedValueOnce(
      new Error("Synthetic identity switch failed"),
    );
    mount();
    await waitFor(() =>
      expect(screen.getByTestId("actor").textContent).toBe("A"),
    );
    await sendAndLeave("Keep A's pending request");
    const requestId = getChatRequest()?.requestId;
    expect(requestId).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Public switch B" }));
    await waitFor(() =>
      expect(api.switchDemoIdentity).toHaveBeenCalledTimes(1),
    );
    expect(screen.getByTestId("actor").textContent).toBe("A");
    expect(getChatRequest()?.requestId).toBe(requestId);
    expect(getChatRequest()?.status).toBe("in_flight");
  });

  it("fences a late create response across A to B to A identity changes", async () => {
    let resolveCreated!: (session: ChatSession) => void;
    api.conversations.mockResolvedValue([]);
    api.createConversation.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveCreated = resolve;
        }),
    );
    openNewChatUrl();
    mount();
    await pickAgentAndDone();
    await waitFor(() =>
      expect(api.createConversation).toHaveBeenCalledTimes(1),
    );
    window.history.replaceState(null, "", "/teacher/chat");

    fireEvent.click(screen.getByRole("button", { name: "Public switch B" }));
    await waitFor(() =>
      expect(screen.getByTestId("actor").textContent).toBe("B"),
    );
    await waitFor(() => expect(api.conversations).toHaveBeenCalledTimes(1));
    await act(async () => resolveCreated(emptyConversation));
    expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
    expect(getChatRequest()).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Public switch A" }));
    await waitFor(() =>
      expect(screen.getByTestId("actor").textContent).toBe("A"),
    );
    await waitFor(() => expect(api.conversations).toHaveBeenCalledTimes(2));
    await screen.findByText("No chats yet.");
    expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
    expect(getChatRequest()).toBeNull();
    expect(api.streamConversation).not.toHaveBeenCalled();
  });

  it("does not let an old same-actor create replace a newer Chat after navigation", async () => {
    let resolveOldCreate!: (session: ChatSession) => void;
    const newerConversation = { ...emptyConversation, id: "newer-chat" };
    api.conversations.mockResolvedValue([]);
    api.createConversation
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveOldCreate = resolve;
          }),
      )
      .mockResolvedValueOnce(newerConversation);
    api.streamConversation.mockImplementationOnce(
      () => new Promise(() => undefined),
    );
    openNewChatUrl();
    mount();
    await pickAgentAndDone();
    await waitFor(() =>
      expect(api.createConversation).toHaveBeenCalledTimes(1),
    );
    fireEvent.click(screen.getByRole("button", { name: "Leave Chats" }));
    fireEvent.click(screen.getByRole("button", { name: "Enter Chats" }));

    const reopenedInput = await chooseAgent();
    fireEvent.change(reopenedInput, {
      target: { value: "New current request" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(api.streamConversation).toHaveBeenCalledTimes(1),
    );
    expect(api.streamConversation.mock.calls[0][0]).toBe("newer-chat");
    const currentRequestId = getChatRequest()?.requestId;
    expect(currentRequestId).toBeTruthy();
    await act(async () => resolveOldCreate(emptyConversation));

    expect(api.createConversation).toHaveBeenCalledTimes(2);
    expect(api.streamConversation).toHaveBeenCalledTimes(1);
    expect(getChatRequest()?.requestId).toBe(currentRequestId);
    expect(getChatRequest()?.status).toBe("in_flight");
  });

  it("keeps a create that settles after leaving the New page off screen", async () => {
    let resolveOldCreate!: (session: ChatSession) => void;
    api.conversations.mockResolvedValue([]);
    api.createConversation.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOldCreate = resolve;
        }),
    );
    openNewChatUrl();
    mount();
    await pickAgentAndDone();
    await waitFor(() =>
      expect(api.createConversation).toHaveBeenCalledTimes(1),
    );
    window.history.replaceState(null, "", "/teacher/chat");
    fireEvent.click(screen.getByRole("button", { name: "Leave Chats" }));
    fireEvent.click(screen.getByRole("button", { name: "Enter Chats" }));
    await screen.findByText("No chats yet.");
    const navigations = routerPush.mock.calls.length;

    await act(async () => resolveOldCreate(emptyConversation));
    expect(routerPush.mock.calls.length).toBe(navigations);
    expect(screen.getByText("No chats yet.")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
    expect(api.createConversation).toHaveBeenCalledTimes(1);
    expect(api.streamConversation).not.toHaveBeenCalled();
    expect(getChatRequest()).toBeNull();
  });
});
