import {
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
  role: "student",
  userId: "team-chat-student",
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    identityGeneration: 1,
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

import { AgentChat } from "../components/agent-chat";
import { AppShell } from "../components/app-shell";
import { LocaleProvider } from "../components/locale";
import { abandonChatRequest } from "../lib/chat-request-store";

const agents = [
  {
    agent_id: "agent-1",
    version_id: "version-1",
    course_id: "course",
    name: "Socrates",
    version_label: "V1.0",
    avatar_config: {},
    available: true,
  },
  {
    agent_id: "agent-2",
    version_id: "version-2",
    course_id: "course",
    name: "Mencius",
    version_label: "V2.0",
    avatar_config: {},
    available: true,
  },
];

const team = {
  id: "team-1",
  course_id: "course",
  owner_user_id: "team-chat-student",
  ownership_scope: "personal",
  group_id: null,
  display_name: "Reasoning circle",
  visibility: "private",
  metadata_revision: 7,
  authorization_epoch: 2,
  current_version_id: "team-version-3",
  current_version_seq: 3,
  member_count: 2,
  can_edit: true,
  members: [
    {
      id: "member-1",
      agent_id: "agent-1",
      agent_version_id: "version-1",
      display_name: "Socrates",
      avatar_config: {},
      position: 0,
      is_leader: true,
      available: true,
    },
    {
      id: "member-2",
      agent_id: "agent-2",
      agent_version_id: "version-2",
      display_name: "Mencius",
      avatar_config: {},
      position: 1,
      is_leader: false,
      available: true,
    },
  ],
  shared_knowledge_set_ids: ["set-1"],
  publication_state: "unpublished",
};

const teamSession = {
  entry_kind: "team" as const,
  chat_visibility: "private" as const,
  origin: "custom_team" as const,
  read_only: false,
  can_send: true,
  id: "conversation-team-1",
  team: {
    id: "team-1",
    version_id: "team-version-3",
    course_id: "course",
    name: "Reasoning circle",
    available: true,
    members: [
      {
        id: "participant-1",
        name: "Bowen",
        avatar_config: {},
        position: 0,
        is_leader: true,
        available: true,
      },
      {
        id: "participant-2",
        name: "Bowen",
        avatar_config: {},
        position: 1,
        is_leader: false,
        available: true,
      },
      {
        id: "participant-3",
        name: "Jade",
        avatar_config: {},
        position: 2,
        is_leader: false,
        available: true,
      },
    ],
  },
  revision: 0,
  turns: [],
  created_at: "2026-09-28T12:00:00Z",
};

const mayaTeam = {
  id: "maya-team-1",
  team_version_id: "maya-version-4",
  course_id: "course",
  display_name: "Course Dialogue Team",
  leader_display_name: "Socrates",
  members: [
    {
      display_name: "Socrates",
      avatar_config: {},
      position: 0,
      is_leader: true,
    },
    {
      display_name: "Mencius",
      avatar_config: {},
      position: 1,
      is_leader: false,
    },
  ],
  published_at: "2026-09-28T12:00:00Z",
};

function renderChats() {
  return render(
    <LocaleProvider initialLocale="en">
      <AppShell role={state.role as "teacher" | "student"}>
        <AgentChat />
      </AppShell>
    </LocaleProvider>,
  );
}

async function openNewChoices() {
  const nav = within(screen.getByRole("navigation"));
  await screen.findByRole("combobox", { name: "Agent" });
  fireEvent.click(await nav.findByRole("button", { name: "New" }));
  await screen.findByRole("heading", { name: "Start a chat" });
}

beforeEach(() => {
  abandonChatRequest();
  state.userId = `team-chat-${Date.now()}-${Math.random()}`;
  state.role = "student";
  state.api = {
    chatAgents: vi.fn().mockResolvedValue(agents),
    conversations: vi.fn().mockResolvedValue([]),
    createTeamConversation: vi.fn().mockResolvedValue(teamSession),
    conversationSessions: vi.fn().mockResolvedValue([]),
    conversationSession: vi.fn().mockResolvedValue(teamSession),
    streamTeamConversation: vi.fn().mockResolvedValue(teamSession),
    createConversation: vi.fn(),
    streamConversation: vi.fn(),
    conversation: vi.fn(),
    deleteConversation: vi.fn(),
    knowledgeSets: vi
      .fn()
      .mockResolvedValue([
        { id: "set-1", display_name: "Shared course notes", can_edit: true },
      ]),
    teams: vi.fn().mockResolvedValue([]),
    team: vi.fn().mockResolvedValue(team),
    mayaTeams: vi.fn().mockResolvedValue([mayaTeam]),
    createTeam: vi.fn().mockResolvedValue(team),
    updateTeam: vi.fn().mockResolvedValue(team),
  };
});

afterEach(() => {
  cleanup();
  abandonChatRequest();
  vi.clearAllMocks();
});

describe("Chats Team entry", () => {
  it("offers Agent, Team, and Maya Team, while New Agent stays on the existing single-Agent path", async () => {
    renderChats();
    await openNewChoices();

    expect(screen.getByRole("button", { name: /New Agent chat/ })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /Create or edit a Team/ }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /Maya Team/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /New Agent chat/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Socrates/ }));
    await screen.findByRole("combobox", { name: "Agent" });
    expect(state.api.createConversation).not.toHaveBeenCalled();
  });

  it("creates a custom Team with ordered member IDs, one Leader, and optional shared Sets, without creating a Chat", async () => {
    renderChats();
    await openNewChoices();
    fireEvent.click(
      screen.getByRole("button", { name: /Create or edit a Team/ }),
    );

    await screen.findByRole("heading", { name: "Your Teams" });
    fireEvent.change(screen.getByLabelText("Team name"), {
      target: { value: "Reasoning circle" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /Socrates/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Mencius/ }));
    fireEvent.click(
      screen.getByRole("radio", { name: "Set Mencius as Leader" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Shared course notes" }),
    );
    fireEvent.click(screen.getByRole("radio", { name: "Public" }));
    fireEvent.click(
      screen.getAllByRole("button", { name: "Create Team" }).at(-1)!,
    );

    await screen.findByText(/Team saved\. You can now start a Team Chat\./);
    expect(state.api.createTeam).toHaveBeenCalledWith(
      "course",
      {
        display_name: "Reasoning circle",
        group_id: null,
        visibility: "public",
        members: [
          { agent_version_id: "version-1", is_leader: false, position: 0 },
          { agent_version_id: "version-2", is_leader: true, position: 1 },
        ],
        shared_knowledge_set_ids: ["set-1"],
      },
      { idempotency: expect.anything() },
    );
    expect(state.api.createConversation).not.toHaveBeenCalled();
    expect(state.api.streamConversation).not.toHaveBeenCalled();
  });

  it("edits a Team through its stable ID and metadata revision, creating the next version", async () => {
    state.api.teams.mockResolvedValue([team]);
    renderChats();
    await openNewChoices();
    fireEvent.click(
      screen.getByRole("button", { name: /Create or edit a Team/ }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    const name = await screen.findByLabelText("Team name");
    fireEvent.change(name, { target: { value: "Reasoning circle v2" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Save new Team version" }),
    );

    await screen.findByText(/Team saved\. You can now start a Team Chat\./);
    expect(state.api.updateTeam).toHaveBeenCalledWith(
      "team-1",
      {
        display_name: "Reasoning circle v2",
        visibility: "private",
        members: [
          { agent_version_id: "version-1", is_leader: true, position: 0 },
          { agent_version_id: "version-2", is_leader: false, position: 1 },
        ],
        shared_knowledge_set_ids: ["set-1"],
        expected_metadata_revision: 7,
      },
      { idempotency: expect.anything() },
    );
    expect(state.api.createConversation).not.toHaveBeenCalled();
  });

  it("checks an ambiguous Team save by replaying the same payload with the same idempotency key", async () => {
    state.api.createTeam
      .mockRejectedValueOnce(new Error("connection reset"))
      .mockResolvedValueOnce(team);
    renderChats();
    await openNewChoices();
    fireEvent.click(
      screen.getByRole("button", { name: /Create or edit a Team/ }),
    );
    fireEvent.change(await screen.findByLabelText("Team name"), {
      target: { value: "Retryable circle" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /Socrates/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Mencius/ }));
    fireEvent.click(
      screen.getByRole("radio", { name: "Set Socrates as Leader" }),
    );
    fireEvent.click(
      screen.getAllByRole("button", { name: "Create Team" }).at(-1)!,
    );

    await screen.findByText(/save result is uncertain/i);
    const firstAttempt = state.api.createTeam.mock.calls[0];
    const firstKey = firstAttempt[2].idempotency.key;
    expect(screen.getByLabelText("Team name").hasAttribute("disabled")).toBe(
      true,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Check save with the same request/ }),
    );

    await screen.findByText(/Team saved\. You can now start a Team Chat\./);
    expect(state.api.createTeam.mock.calls[1][0]).toBe("course");
    expect(state.api.createTeam.mock.calls[1][1]).toEqual(firstAttempt[1]);
    expect(state.api.createTeam.mock.calls[1][2].idempotency.key).toBe(
      firstKey,
    );
    expect(state.api.createConversation).not.toHaveBeenCalled();
  });

  it("does not repeat a successful Team POST when the following list refresh fails", async () => {
    state.api.teams
      .mockResolvedValueOnce([])
      .mockRejectedValueOnce(new Error("list temporarily unavailable"))
      .mockResolvedValueOnce([team]);
    renderChats();
    await openNewChoices();
    fireEvent.click(
      screen.getByRole("button", { name: /Create or edit a Team/ }),
    );
    fireEvent.change(await screen.findByLabelText("Team name"), {
      target: { value: "Reasoning circle" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /Socrates/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Mencius/ }));
    fireEvent.click(
      screen.getByRole("radio", { name: "Set Socrates as Leader" }),
    );
    fireEvent.click(
      screen.getAllByRole("button", { name: "Create Team" }).at(-1)!,
    );

    await screen.findByText(/Team saved\. You can now start a Team Chat\./);
    expect(
      await screen.findByText(
        "Team was saved, but the list could not be refreshed.",
      ),
    ).toBeTruthy();
    expect(state.api.createTeam).toHaveBeenCalledTimes(1);
    const saveKey = state.api.createTeam.mock.calls[0][2].idempotency.key;
    expect(screen.getByText("Reasoning circle")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Refresh Team list" }));
    await waitFor(() =>
      expect(screen.getByText("Reasoning circle")).toBeTruthy(),
    );
    expect(state.api.createTeam).toHaveBeenCalledTimes(1);
    expect(state.api.createTeam.mock.calls[0][2].idempotency.key).toBe(saveKey);
    expect(state.api.teams).toHaveBeenCalledTimes(3);
    expect(state.api.createConversation).not.toHaveBeenCalled();
  });

  it("lets a Student choose only a catalog Team and Chat privacy, never member or Knowledge configuration", async () => {
    renderChats();
    await openNewChoices();
    fireEvent.click(screen.getByRole("button", { name: /Maya Team/ }));

    const directoryCard = await screen.findByLabelText(/Course Dialogue Team/);
    fireEvent.click(directoryCard);
    fireEvent.click(screen.getByRole("radio", { name: "Public" }));

    expect(
      screen.getByRole("button", { name: "Start Team Chat" }),
    ).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByText("Shared Knowledge")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Start Team Chat" }));
    await screen.findByRole("heading", { name: /Reasoning circle/ });
    expect(state.api.createTeamConversation).toHaveBeenCalledWith(
      { kind: "maya_team", team_id: "maya-team-1" },
      "public",
    );
    expect(state.api.createConversation).not.toHaveBeenCalled();
    expect(state.api.streamConversation).not.toHaveBeenCalled();
  });

  it("does not let an old directory response appear after an identity switch", async () => {
    let resolveOldDirectory!: (result: (typeof mayaTeam)[]) => void;
    state.api.mayaTeams.mockReturnValue(
      new Promise((resolve) => {
        resolveOldDirectory = resolve;
      }),
    );
    const view = renderChats();
    await openNewChoices();
    fireEvent.click(screen.getByRole("button", { name: /Maya Team/ }));
    await waitFor(() => expect(state.api.mayaTeams).toHaveBeenCalledTimes(1));

    const nextDirectoryTeam = {
      ...mayaTeam,
      id: "other-actor-team",
      display_name: "Other actor directory item",
    };
    state.userId = "different-student";
    state.api = {
      ...state.api,
      chatAgents: vi.fn().mockResolvedValue(agents),
      conversations: vi.fn().mockResolvedValue([]),
      mayaTeams: vi.fn().mockResolvedValue([nextDirectoryTeam]),
    };
    view.rerender(
      <LocaleProvider initialLocale="en">
        <AppShell role="student">
          <AgentChat />
        </AppShell>
      </LocaleProvider>,
    );

    await screen.findByRole("combobox", { name: "Agent" });
    await openNewChoices();
    fireEvent.click(screen.getByRole("button", { name: /Maya Team/ }));
    expect(await screen.findByText("Other actor directory item")).toBeTruthy();
    resolveOldDirectory([mayaTeam]);
    await Promise.resolve();

    expect(screen.getByText("Other actor directory item")).toBeTruthy();
    expect(screen.queryByText("Course Dialogue Team")).toBeNull();
  });

  it("keeps student Teams and Chats separate from the published Maya Team directory", async () => {
    state.role = "teacher";
    state.api.teams.mockResolvedValue([team]);
    renderChats();
    await openNewChoices();
    fireEvent.click(
      screen.getByRole("button", { name: /Create or edit a Team/ }),
    );

    expect(await screen.findByText("Reasoning circle")).toBeTruthy();
    expect(state.api.mayaTeams).not.toHaveBeenCalled();
    expect(state.api.teams).toHaveBeenCalledWith("course");
  });

  it("routes typed @ recipients by frozen participant IDs and keeps pasted code mentions as plain text", async () => {
    renderChats();
    await openNewChoices();
    fireEvent.click(screen.getByRole("button", { name: /Maya Team/ }));
    fireEvent.click(await screen.findByLabelText(/Course Dialogue Team/));
    fireEvent.click(screen.getByRole("button", { name: "Start Team Chat" }));
    const message = await screen.findByRole("textbox", { name: "Message" });

    fireEvent.keyDown(message, { key: "@", shiftKey: true });
    expect(screen.getByRole("group", { name: "Recipients" })).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: "@All members" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /@Bowen · 1/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /@Jade · 3/ }));
    const recipientGroup = within(
      screen.getByRole("group", { name: "Recipients" }),
    );
    expect(
      (
        recipientGroup.getByRole("checkbox", {
          name: /@Bowen · 1/,
        }) as HTMLInputElement
      ).checked,
    ).toBe(true);
    expect(
      (
        recipientGroup.getByRole("checkbox", {
          name: /@Jade · 3/,
        }) as HTMLInputElement
      ).checked,
    ).toBe(true);

    const pastedText = "```txt\n@All members @Bowen\n``` this is quoted text";
    fireEvent.change(message, { target: { value: pastedText } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(1),
    );
    expect(state.api.streamTeamConversation.mock.calls[0][0]).toBe(
      "conversation-team-1",
    );
    expect(state.api.streamTeamConversation.mock.calls[0][1]).toMatchObject({
      message: pastedText,
      routing: {
        mode: "selected",
        participant_ids: ["participant-1", "participant-3"],
      },
    });
  });

  it("shows participant-named partial results without claiming a full reply", async () => {
    const requestId = "team-request-1";
    const partialSession = {
      ...teamSession,
      revision: 2,
      turns: [
        {
          id: requestId,
          user_text: "Compare these views",
          assistant_text: null,
          mode: "mock" as const,
          state: "partial" as const,
          sources: [],
          safe_error_code: null,
          routing: { mode: "all" as const, participant_ids: [] },
          member_results: [
            {
              id: "result-1",
              participant_id: "participant-1",
              speaker_name: "Bowen",
              ordinal: 0,
              state: "ready" as const,
              assistant_text: "The first view.",
              sources: [],
              safe_error_code: null,
            },
            {
              id: "result-2",
              participant_id: "participant-2",
              speaker_name: "Bowen",
              ordinal: 1,
              state: "failed" as const,
              assistant_text: null,
              sources: [],
              safe_error_code: "member_reply_failed",
            },
          ],
        },
      ],
    };
    state.api.streamTeamConversation.mockResolvedValue(partialSession);
    renderChats();
    await openNewChoices();
    fireEvent.click(screen.getByRole("button", { name: /Maya Team/ }));
    fireEvent.click(await screen.findByLabelText(/Course Dialogue Team/));
    fireEvent.click(screen.getByRole("button", { name: "Start Team Chat" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "Message" }), {
      target: { value: "Compare these views" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("The first view.")).toBeTruthy();
    expect(
      screen.getByText(
        "Some members could not reply. Successful replies are kept.",
      ),
    ).toBeTruthy();
    expect(screen.getAllByRole("heading", { name: /Bowen/ })).toHaveLength(2);
    expect(
      screen.getByRole("heading", { name: /Bowen · leader/ }),
    ).toBeTruthy();
  });

  it("does not send Enter during Chinese IME composition", async () => {
    renderChats();
    await openNewChoices();
    fireEvent.click(screen.getByRole("button", { name: /Maya Team/ }));
    fireEvent.click(await screen.findByLabelText(/Course Dialogue Team/));
    fireEvent.click(screen.getByRole("button", { name: "Start Team Chat" }));
    const message = await screen.findByRole("textbox", { name: "Message" });
    fireEvent.change(message, { target: { value: "你好" } });

    fireEvent.keyDown(message, { key: "Enter", isComposing: true });
    expect(state.api.streamTeamConversation).not.toHaveBeenCalled();
    fireEvent.keyDown(message, { key: "Enter", isComposing: false });
    await waitFor(() =>
      expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(1),
    );
    expect(state.api.streamTeamConversation.mock.calls[0][1].message).toBe(
      "你好",
    );
  });

  it("does not resend an unknown Team request when the user checks its status", async () => {
    state.api.streamTeamConversation.mockRejectedValueOnce(
      new Error("connection reset"),
    );
    renderChats();
    await openNewChoices();
    fireEvent.click(screen.getByRole("button", { name: /Maya Team/ }));
    fireEvent.click(await screen.findByLabelText(/Course Dialogue Team/));
    fireEvent.click(screen.getByRole("button", { name: "Start Team Chat" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "Message" }), {
      target: { value: "Do not duplicate this turn" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByRole("button", { name: "Check Team Chat status" });
    const requestId =
      state.api.streamTeamConversation.mock.calls[0][1].request_id;
    state.api.conversationSession.mockResolvedValue({
      ...teamSession,
      revision: 1,
      turns: [
        {
          id: requestId,
          user_text: "Do not duplicate this turn",
          assistant_text: null,
          mode: "mock",
          state: "acceptance_unknown",
          sources: [],
          safe_error_code: "chat_acceptance_unknown",
          routing: { mode: "all", participant_ids: [] },
          member_results: [],
        },
      ],
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Check Team Chat status" }),
    );
    await waitFor(() =>
      expect(state.api.conversationSession).toHaveBeenCalledWith(
        "conversation-team-1",
      ),
    );
    expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText(/outcome is unknown/i).length).toBeGreaterThan(
      0,
    );
  });
});
