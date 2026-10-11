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
  role: "student",
  userId: "team-chat-student",
}));
const navigation = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
const originalVisibilityDescriptor = Object.getOwnPropertyDescriptor(
  document,
  "visibilityState",
);

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
  useSearchParams: () => new URLSearchParams(window.location.search),
  useRouter: () => navigation,
}));

import { AgentChat } from "../components/agent-chat";
import { AppShell } from "../components/app-shell";
import { TeamEntryFlow } from "../components/chats/team-entry-flow";
import { GroupWorkspace } from "../components/student-workspace";
import { TeacherStudyformWorkspace } from "../components/teacher-workspace";
import { LocaleProvider } from "../components/locale";
import { UiGuideTooltip } from "../components/ui-guide-tooltip";
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

const publicTeam = { ...team, visibility: "public" };

function renderChats() {
  return render(
    <LocaleProvider initialLocale="en">
      <UiGuideTooltip />
      <AppShell role={state.role as "teacher" | "student"}>
        <AgentChat />
      </AppShell>
    </LocaleProvider>,
  );
}

function teamManagementPage(
  initialRouteMode = "teams",
  initialTeamId?: string,
) {
  return (
    <LocaleProvider initialLocale="en">
      <AppShell role="teacher">
        <TeamEntryFlow
          api={state.api as never}
          courseId="course"
          agents={agents as never}
          standalone
          backHref="/teacher/studyform"
          initialRouteMode={initialRouteMode}
          initialTeamId={initialTeamId}
        />
      </AppShell>
    </LocaleProvider>
  );
}

function renderTeamManagement(
  initialRouteMode = "teams",
  initialTeamId?: string,
) {
  return render(teamManagementPage(initialRouteMode, initialTeamId));
}

function sidebarButton(name: string) {
  return within(screen.getByRole("navigation")).getByRole("button", {
    name,
  }) as HTMLButtonElement;
}

async function startNewTeam() {
  await screen.findByLabelText("Name");
}

async function fillTeamForm(name: string, leader = "Socrates") {
  fireEvent.change(await screen.findByLabelText("Name"), {
    target: { value: name },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: /Socrates/ }));
  fireEvent.click(screen.getByRole("checkbox", { name: /Mencius/ }));
  fireEvent.click(
    screen.getByRole("radio", { name: `Set ${leader} as Leader` }),
  );
}

async function openNewChat() {
  const nav = within(screen.getByRole("navigation"));
  const create = await nav.findByRole("button", { name: "New" });
  await waitFor(() =>
    expect((create as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(create);
}

// New lists Teams and Agents as tiles; the sidebar Done creates the Chat.
async function chooseTarget(tileName: string | RegExp) {
  await openNewChat();
  fireEvent.click(await screen.findByRole("button", { name: tileName }));
  const done = sidebarButton("Done");
  await waitFor(() => expect(done.disabled).toBe(false));
  fireEvent.click(done);
}

async function sendMessage(message: string) {
  fireEvent.change(await screen.findByRole("textbox", { name: "Message" }), {
    target: { value: message },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

async function startMayaTeamChat(message: string) {
  await chooseTarget(/Course Dialogue Team/);
  await screen.findByRole("textbox", { name: "Message" });
  await sendMessage(message);
}

beforeEach(() => {
  abandonChatRequest();
  window.history.replaceState(null, "", "/student/chat");
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
    knowledgeSets: vi.fn().mockResolvedValue([
      {
        id: "hidden-set",
        display_name: "Hidden outside Brainform",
        can_edit: true,
      },
    ]),
    brainformKnowledge: vi.fn().mockResolvedValue([
      {
        agent_id: null,
        canonical_set_id: "set-1",
        source_agent_display_name: "Course Dialogue Team",
        knowledge_display_name: "Shared course notes",
        generation_job_id: null,
        can_read: true,
        can_edit: true,
        version_seq: 1,
        content_hash: null,
        generation_state: null,
        safe_error_code: null,
      },
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
  vi.useRealTimers();
  if (originalVisibilityDescriptor) {
    Object.defineProperty(
      document,
      "visibilityState",
      originalVisibilityDescriptor,
    );
  } else {
    Reflect.deleteProperty(document, "visibilityState");
  }
  abandonChatRequest();
  vi.clearAllMocks();
});

describe("Studyform Teams", () => {
  beforeEach(() => {
    state.role = "teacher";
    state.api.createTeam.mockResolvedValue(publicTeam);
    state.api.updateTeam.mockResolvedValue(publicTeam);
  });

  it("opens the Maya Team form when a mounted Studyform route changes to team-new", async () => {
    const view = renderTeamManagement("teams");
    await screen.findByRole("heading", { level: 2, name: "Teams" });
    view.rerender(teamManagementPage("team-new"));
    expect(await screen.findByLabelText("Name")).toBeTruthy();
    expect(sidebarButton("Done")).toBeTruthy();
    expect(
      within(screen.getByRole("main")).queryByRole("button", { name: "Done" }),
    ).toBeNull();
    expect(
      within(screen.getByRole("main")).queryByRole("button", {
        name: "Publish",
      }),
    ).toBeNull();
    expect(
      within(screen.getByRole("main")).queryByRole("button", { name: "Save" }),
    ).toBeNull();
  });

  it("lists every readable Team on one Teams surface", async () => {
    state.api.teams.mockResolvedValue([
      publicTeam,
      { ...team, id: "private-team", display_name: "Private circle" },
      {
        ...publicTeam,
        id: "group-team",
        display_name: "Group circle",
        group_id: "group-1",
      },
      {
        ...publicTeam,
        id: "readable-team",
        display_name: "Readable circle",
        can_edit: false,
      },
    ]);
    renderTeamManagement();
    expect(await screen.findByText("Reasoning circle")).toBeTruthy();
    expect(screen.getByText("Private circle")).toBeTruthy();
    expect(screen.getByText("Group circle")).toBeTruthy();
    expect(screen.getByText("Readable circle")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Public" })).toBeNull();
    expect(
      within(screen.getByRole("navigation")).queryByRole("button", {
        name: "New",
      }),
    ).toBeNull();
  });

  it("shows members, the Leader and selected Brainform names without letting a reader change them", async () => {
    state.api.team.mockResolvedValue({
      ...publicTeam,
      can_edit: false,
      display_name: "Readable circle",
    });
    renderTeamManagement("team-edit", "team-1");
    const name = (await screen.findByLabelText("Name")) as HTMLInputElement;
    expect(name.disabled).toBe(true);
    expect(name.value).toBe("Readable circle");
    const member = screen.getByRole("checkbox", {
      name: /Socrates/,
    }) as HTMLInputElement;
    expect(member.checked).toBe(true);
    expect(member.disabled).toBe(true);
    const leader = screen.getByRole("radio", {
      name: "Set Socrates as Leader",
    }) as HTMLInputElement;
    expect(leader.checked).toBe(true);
    expect(leader.disabled).toBe(true);
    const knowledge = screen.getByRole("checkbox", {
      name: "Shared course notes",
    }) as HTMLInputElement;
    expect(knowledge.checked).toBe(true);
    expect(knowledge.disabled).toBe(true);
    expect(
      screen.queryByRole("checkbox", { name: "Hidden outside Brainform" }),
    ).toBeNull();
    expect(
      within(screen.getByRole("navigation")).queryByRole("button", {
        name: "Done",
      }),
    ).toBeNull();
    expect(sidebarButton("Back")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Public" })).toBeNull();
  });

  it("does not navigate the current page when a Team save receipt arrives after unmount", async () => {
    let finishSave!: (saved: typeof team) => void;
    state.api.createTeam.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishSave = resolve;
        }),
    );
    const view = renderTeamManagement("team-new");
    await screen.findByRole("heading", { level: 2, name: "Teams" });
    await startNewTeam();
    await fillTeamForm("Pending circle");
    navigation.push.mockClear();
    const save = sidebarButton("Done");
    await waitFor(() => expect(save.disabled).toBe(false));
    fireEvent.click(save);
    await waitFor(() => expect(state.api.createTeam).toHaveBeenCalledTimes(1));

    view.unmount();
    await act(async () => {
      finishSave(publicTeam);
    });

    expect(navigation.push).not.toHaveBeenCalled();
    expect(state.api.createTeam).toHaveBeenCalledTimes(1);
  });

  it("publishes a Maya Team as a public personal Team from the Studyform sidebar", async () => {
    const view = renderTeamManagement();
    await screen.findByRole("heading", { level: 2, name: "Teams" });
    expect(screen.getByText("No Teams yet.")).toBeTruthy();
    expect(
      within(screen.getByRole("navigation")).queryByRole("button", {
        name: "New",
      }),
    ).toBeNull();
    view.rerender(teamManagementPage("team-new"));
    await startNewTeam();
    fireEvent.click(screen.getByRole("button", { name: "Public" }));
    await fillTeamForm("Reasoning circle", "Mencius");
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Shared course notes" }),
    );
    expect(
      screen.queryByRole("checkbox", { name: "Hidden outside Brainform" }),
    ).toBeNull();
    fireEvent.click(sidebarButton("Done"));
    await screen.findByText("Team saved. You can now start a Team Chat.");
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
  });

  it("edits a Maya Team through its stable ID and metadata revision", async () => {
    state.api.teams.mockResolvedValue([publicTeam]);
    state.api.team.mockResolvedValue(publicTeam);
    renderTeamManagement();
    await screen.findByRole("heading", { level: 2, name: "Teams" });
    fireEvent.click(
      await screen.findByRole("button", { name: "Reasoning circle" }),
    );

    const name = await screen.findByLabelText("Name");
    expect(navigation.push).toHaveBeenCalledWith(
      "/teacher/chat?mode=team-edit&team_id=team-1",
      { scroll: false },
    );
    fireEvent.change(name, { target: { value: "Reasoning circle v2" } });
    fireEvent.click(sidebarButton("Done"));

    await screen.findByText("Team saved. You can now start a Team Chat.");
    expect(state.api.updateTeam).toHaveBeenCalledWith(
      "team-1",
      {
        display_name: "Reasoning circle v2",
        visibility: "public",
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

  it("loads the new routed Team edit while an older Team request is still pending", async () => {
    const nextTeam = { ...team, id: "team-2", display_name: "Second circle" };
    let resolveFirst!: (value: typeof team) => void;
    const firstRequest = new Promise<typeof team>((resolve) => {
      resolveFirst = resolve;
    });
    state.api.teams.mockResolvedValue([team, nextTeam]);
    state.api.team.mockImplementation((teamId: string) =>
      teamId === "team-1" ? firstRequest : Promise.resolve(nextTeam),
    );
    const view = renderTeamManagement("team-edit", "team-1");
    await waitFor(() => expect(state.api.team).toHaveBeenCalledWith("team-1"));

    view.rerender(teamManagementPage("team-edit", "team-2"));
    await waitFor(() => expect(state.api.team).toHaveBeenCalledWith("team-2"));
    const name = await screen.findByLabelText("Name");
    await waitFor(() =>
      expect((name as HTMLInputElement).value).toBe("Second circle"),
    );

    await act(async () => resolveFirst(team));
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe(
      "Second circle",
    );
  });

  it("checks an ambiguous Team save by replaying the same payload with the same idempotency key", async () => {
    state.api.createTeam
      .mockRejectedValueOnce(new Error("connection reset"))
      .mockResolvedValueOnce(publicTeam);
    renderTeamManagement("team-new");
    await screen.findByRole("heading", { level: 2, name: "Teams" });
    await startNewTeam();
    await fillTeamForm("Retryable circle");
    fireEvent.click(sidebarButton("Done"));

    await screen.findByText(/save result is uncertain/i);
    const firstAttempt = state.api.createTeam.mock.calls[0];
    const firstKey = firstAttempt[2].idempotency.key;
    expect(screen.getByLabelText("Name").hasAttribute("disabled")).toBe(true);
    const retrySave = sidebarButton("Done");
    await waitFor(() => expect(retrySave.disabled).toBe(false));
    fireEvent.click(retrySave);

    await waitFor(() => expect(state.api.createTeam).toHaveBeenCalledTimes(2));
    await screen.findByText("Team saved. You can now start a Team Chat.");
    expect(state.api.createTeam.mock.calls[1][0]).toBe("course");
    expect(state.api.createTeam.mock.calls[1][1]).toEqual(firstAttempt[1]);
    expect(state.api.createTeam.mock.calls[1][2].idempotency.key).toBe(
      firstKey,
    );
    expect(state.api.createConversation).not.toHaveBeenCalled();
  });

  it("leaves a saved Team without showing its version list or repeating the POST", async () => {
    state.api.teams.mockResolvedValueOnce([]);
    renderTeamManagement("team-new");
    await screen.findByRole("heading", { level: 2, name: "Teams" });
    await startNewTeam();
    await fillTeamForm("Reasoning circle");
    fireEvent.click(sidebarButton("Done"));

    await screen.findByText("Team saved. You can now start a Team Chat.");
    expect(
      screen.queryByText(
        "Team was saved, but the list could not be refreshed.",
      ),
    ).toBeNull();
    expect(state.api.createTeam).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Version 1")).toBeNull();
    expect(navigation.push).toHaveBeenCalledWith(
      expect.stringContaining("mode=teams"),
      { scroll: false },
    );
    expect(state.api.createConversation).not.toHaveBeenCalled();
  });
});

describe("Studyform Team cards", () => {
  it("lists Agents, Teams and Voices in that order", async () => {
    state.role = "teacher";
    state.api.workspaceAgents = vi.fn().mockResolvedValue([]);
    state.api.teams.mockResolvedValue([
      { ...team, display_name: "Private circle" },
      {
        ...publicTeam,
        id: "published-team",
        display_name: "Course Dialogue Team",
      },
      {
        ...publicTeam,
        id: "group-team",
        display_name: "Group circle",
        group_id: "group-1",
      },
    ]);
    render(
      <LocaleProvider initialLocale="en">
        <TeacherStudyformWorkspace />
      </LocaleProvider>,
    );

    const headings = await screen.findAllByRole("heading", { level: 2 });
    expect(headings.map((heading) => heading.textContent)).toEqual([
      "Agents",
      "Teams",
      "Voices",
    ]);
    expect(
      screen.getByRole("link", { name: "Private circle" }).getAttribute("href"),
    ).toBe("/teacher/studyform?mode=team-edit&team_id=team-1");
    expect(
      screen
        .getByRole("link", { name: "Course Dialogue Team" })
        .getAttribute("href"),
    ).toBe("/teacher/studyform?mode=team-edit&team_id=published-team");
    expect(
      screen.getByRole("link", { name: "Group circle" }).getAttribute("href"),
    ).toBe("/teacher/studyform?mode=team-edit&team_id=group-team");
    expect(
      screen
        .getAllByRole("link", { name: "New" })
        .map((link) => link.getAttribute("href")),
    ).toEqual(["/teacher/agents/new", "/teacher/studyform?mode=team-new"]);
  });

  it("lets a student create a private Team beside Agents and Voices", async () => {
    state.api.group = vi.fn().mockResolvedValue({
      id: "group-1",
      course_id: "course",
      name: "Demo",
    });
    state.api.agents = vi.fn().mockResolvedValue([]);
    state.api.versions = vi.fn().mockResolvedValue([]);
    state.api.voiceProfiles = vi.fn().mockResolvedValue([]);
    state.api.teams.mockResolvedValue([
      { ...team, display_name: "Private circle" },
      {
        ...publicTeam,
        id: "published-team",
        display_name: "Course Dialogue Team",
      },
    ]);
    render(
      <LocaleProvider initialLocale="en">
        <GroupWorkspace groupId="group-1" />
      </LocaleProvider>,
    );

    const headings = await screen.findAllByRole("heading", { level: 2 });
    expect(headings.map((heading) => heading.textContent)).toEqual([
      "Agents",
      "Teams",
      "Voices",
    ]);
    expect(
      screen
        .getByRole("link", { name: "Course Dialogue Team" })
        .getAttribute("href"),
    ).toBe("/student/groups/group-1?mode=team-edit&team_id=published-team");
    expect(
      screen.getByRole("link", { name: "Private circle" }).getAttribute("href"),
    ).toBe("/student/groups/group-1?mode=team-edit&team_id=team-1");
    expect(
      screen
        .getAllByRole("link", { name: "New" })
        .map((link) => link.getAttribute("href")),
    ).toEqual([
      "/student/groups/group-1/agents/new",
      "/student/groups/group-1?mode=team-new",
    ]);
  });

  it("does not offer Team creation on a teacher's group visit", async () => {
    state.role = "teacher";
    state.api.group = vi.fn().mockResolvedValue({
      id: "group-1",
      course_id: "course",
      name: "Demo",
    });
    state.api.agents = vi.fn().mockResolvedValue([]);
    state.api.versions = vi.fn().mockResolvedValue([]);
    state.api.voiceProfiles = vi.fn().mockResolvedValue([]);
    render(
      <LocaleProvider initialLocale="en">
        <GroupWorkspace groupId="group-1" initialMode="team-new" />
      </LocaleProvider>,
    );

    await screen.findByRole("heading", { name: "Agents" });
    expect(screen.queryByRole("heading", { name: "Teams" })).toBeNull();
    expect(screen.queryByLabelText("Name")).toBeNull();
    expect(screen.queryByRole("link", { name: "New" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Voices" })).toBeTruthy();
  });
});

describe("Chatform", () => {
  it.each(["student", "teacher"])(
    "shows No chats yet before any Chat exists for a %s",
    async (role) => {
      state.role = role;
      renderChats();
      expect(await screen.findByText("No chats yet.")).toBeTruthy();
      expect(
        screen.queryByText("Click New and start chatting with me!"),
      ).toBeNull();
      expect(
        within(screen.getByRole("main")).queryByRole("button", { name: "New" }),
      ).toBeNull();
      expect(
        within(screen.getByRole("navigation")).getByRole("button", {
          name: "New",
        }),
      ).toBeTruthy();
      expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
      expect(screen.queryByRole("combobox", { name: "Chat with" })).toBeNull();
    },
  );

  it("lists Teams and Agents on the New page and creates nothing until Done", async () => {
    state.api.teams.mockResolvedValue([
      { ...team, can_edit: false, visibility: "public" },
    ]);
    renderChats();
    await openNewChat();
    const page = within(screen.getByRole("main"));
    const socrates = await page.findByRole("button", { name: /Socrates/ });
    expect(page.getByRole("heading", { name: "Teams" })).toBeTruthy();
    expect(page.getByRole("heading", { name: "Agents" })).toBeTruthy();
    expect(page.getByRole("button", { name: /Mencius/ })).toBeTruthy();
    expect(page.getByRole("button", { name: /Reasoning circle/ })).toBeTruthy();
    expect(
      page.getByRole("button", { name: /Course Dialogue Team/ }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Private" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Public" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
    expect(screen.queryByLabelText("Name")).toBeNull();
    expect(sidebarButton("Done").disabled).toBe(true);

    fireEvent.click(socrates);
    expect(socrates.getAttribute("aria-pressed")).toBe("true");
    expect(sidebarButton("Done").disabled).toBe(false);
    fireEvent.click(socrates);
    expect(socrates.getAttribute("aria-pressed")).toBe("false");
    expect(sidebarButton("Done").disabled).toBe(true);
    fireEvent.click(sidebarButton("Done"));
    expect(state.api.createConversation).not.toHaveBeenCalled();
    expect(state.api.createTeamConversation).not.toHaveBeenCalled();
  });

  it("creates a private Agent Chat on Done, before any message", async () => {
    state.api.createConversation.mockResolvedValue({
      id: "conversation-agent-1",
      entry_kind: "agent",
      chat_visibility: "private",
      origin: "single_agent",
      read_only: false,
      can_send: true,
      agent: agents[0],
      revision: 0,
      turns: [],
      created_at: "2026-10-11T00:00:00Z",
    });
    renderChats();
    await chooseTarget(/Socrates/);

    await waitFor(() =>
      expect(state.api.createConversation).toHaveBeenCalledWith("version-1"),
    );
    expect(state.api.createConversation).toHaveBeenCalledTimes(1);
    expect(state.api.createTeamConversation).not.toHaveBeenCalled();
    expect(
      await screen.findByRole("heading", { level: 2, name: "Socrates" }),
    ).toBeTruthy();
    expect(screen.getByText("Agent")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Message" })).toBeTruthy();
    expect(state.api.streamConversation).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Done" })).toBeNull();
  });

  it("keeps the New page when Done cannot create the Chat", async () => {
    state.api.createConversation.mockRejectedValue(new Error("stop here"));
    renderChats();
    await chooseTarget(/Socrates/);
    await waitFor(() =>
      expect(state.api.createConversation).toHaveBeenCalledTimes(1),
    );
    expect(
      await within(screen.getByRole("main")).findByRole("button", {
        name: /Socrates/,
      }),
    ).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
    await waitFor(() => expect(sidebarButton("Done").disabled).toBe(false));
  });

  it("starts a Chat with a readable Team without exposing Team management", async () => {
    state.api.teams.mockResolvedValue([
      { ...team, can_edit: false, visibility: "public" },
    ]);
    renderChats();
    await chooseTarget(/Reasoning circle/);
    await waitFor(() =>
      expect(state.api.createTeamConversation).toHaveBeenCalledWith({
        kind: "team",
        team_id: "team-1",
        team_version_id: "team-version-3",
      }),
    );
    await screen.findByRole("textbox", { name: "Message" });
    expect(screen.getByText("Team")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByLabelText("Name")).toBeNull();
    expect(state.api.streamTeamConversation).not.toHaveBeenCalled();

    await sendMessage("Open the discussion");
    await waitFor(() =>
      expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(1),
    );
    expect(state.api.createTeamConversation).toHaveBeenCalledTimes(1);
    expect(state.api.streamTeamConversation.mock.calls[0][0]).toBe(
      "conversation-team-1",
    );
    expect(state.api.streamTeamConversation.mock.calls[0][1]).toMatchObject({
      message: "Open the discussion",
      routing: { mode: "selected", participant_ids: ["participant-1"] },
    });
    expect(state.api.createTeam).not.toHaveBeenCalled();
    expect(state.api.updateTeam).not.toHaveBeenCalled();
  });

  it("creates a private Team from Studyform and does not start a Chat", async () => {
    state.role = "teacher";
    state.api.workspaceAgents = vi.fn().mockResolvedValue([]);
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherStudyformWorkspace initialMode="team-new" />
        </AppShell>
      </LocaleProvider>,
    );
    await screen.findByRole("heading", { level: 2, name: "Teams" });
    expect(
      screen
        .getByRole("button", { name: "Private" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    await fillTeamForm("Reasoning circle");
    const done = sidebarButton("Done");
    await waitFor(() => expect(done.disabled).toBe(false));
    fireEvent.click(done);

    await screen.findByText("Team saved. You can now start a Team Chat.");
    expect(state.api.createTeam).toHaveBeenCalledWith(
      "course",
      {
        display_name: "Reasoning circle",
        group_id: null,
        visibility: "private",
        members: [
          { agent_version_id: "version-1", is_leader: true, position: 0 },
          { agent_version_id: "version-2", is_leader: false, position: 1 },
        ],
        shared_knowledge_set_ids: [],
      },
      { idempotency: expect.anything() },
    );
    expect(state.api.createTeamConversation).not.toHaveBeenCalled();
    expect(state.api.createConversation).not.toHaveBeenCalled();
  });

  it("leaves the private Team form without creating one", async () => {
    state.role = "teacher";
    state.api.workspaceAgents = vi.fn().mockResolvedValue([]);
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherStudyformWorkspace initialMode="team-new" />
        </AppShell>
      </LocaleProvider>,
    );
    await screen.findByLabelText("Name");
    fireEvent.click(sidebarButton("Back"));

    expect(screen.queryByLabelText("Name")).toBeNull();
    expect(state.api.createTeam).not.toHaveBeenCalled();
  });

  it("lets a Student choose only a catalog Team, never member or Knowledge configuration", async () => {
    renderChats();
    await openNewChat();
    fireEvent.click(
      await screen.findByRole("button", { name: /Course Dialogue Team/ }),
    );
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByText("Shared Knowledge")).toBeNull();
    fireEvent.click(sidebarButton("Done"));
    await waitFor(() =>
      expect(state.api.createTeamConversation).toHaveBeenCalledWith({
        kind: "team",
        team_id: "maya-team-1",
        team_version_id: "maya-version-4",
      }),
    );
    await screen.findByRole("heading", { level: 2, name: "Reasoning circle" });
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(state.api.createConversation).not.toHaveBeenCalled();
    expect(state.api.streamConversation).not.toHaveBeenCalled();
  });

  it("lists a Teacher's own published Team only once, under Teams", async () => {
    state.role = "teacher";
    state.api.teams.mockResolvedValue([
      {
        ...publicTeam,
        id: "maya-team-1",
        display_name: "Course Dialogue Team",
      },
      { ...team, can_edit: false, visibility: "public" },
    ]);
    renderChats();
    await openNewChat();
    const page = within(screen.getByRole("main"));
    await page.findByRole("button", { name: /Course Dialogue Team/ });
    expect(
      page.getAllByRole("button", { name: /Course Dialogue Team/ }),
    ).toHaveLength(1);
    expect(page.getByRole("button", { name: /Reasoning circle/ })).toBeTruthy();
    expect(state.api.teams).toHaveBeenCalledWith("course");
    expect(state.api.mayaTeams).toHaveBeenCalledWith("course");
  });

  it("shows no privacy or target controls on an existing Chat", async () => {
    const history = {
      ...teamSession,
      turns: [
        {
          id: "private-turn",
          user_text: "A private Team question",
          state: "ready",
          member_results: [],
        },
      ],
    };
    state.api.conversationSessions.mockResolvedValue([history]);
    state.api.conversationSession.mockResolvedValue(history);
    renderChats();
    fireEvent.click(
      await screen.findByRole("button", { name: "A private Team question" }),
    );
    const log = await screen.findByRole("log");
    await within(log).findByText("A private Team question");
    expect(screen.queryByRole("button", { name: "Private" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Public" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Chat with" })).toBeNull();
    expect(within(log).getByText("A private Team question")).toBeTruthy();
    expect(state.api.createTeamConversation).not.toHaveBeenCalled();
    expect(state.api.streamTeamConversation).not.toHaveBeenCalled();
  });

  it("shows the Name on keyboard focus without a delayed native title", async () => {
    const history = {
      ...teamSession,
      turns: [
        {
          id: "history-turn",
          user_text: "A previous Team question",
          state: "ready",
          member_results: [],
        },
      ],
    };
    state.api.conversationSessions.mockResolvedValue([history]);
    renderChats();

    const entry = await screen.findByRole("button", {
      name: "A previous Team question",
    });
    expect(entry.getAttribute("title")).toBeNull();
    expect(entry.getAttribute("data-ui-guide")).toBe("chat.history");
    fireEvent.keyDown(document, { key: "Tab" });
    fireEvent.focusIn(entry);
    expect(screen.getByRole("tooltip").textContent).toBe("Reasoning circle");
  });

  it("uses one immediate guide for read-only Team Send and keeps it disabled", async () => {
    const readOnly = {
      ...teamSession,
      read_only: true,
      can_send: false,
      turns: [
        {
          id: "readonly-turn",
          user_text: "Read-only history",
          state: "ready",
          member_results: [],
        },
      ],
    };
    state.api.conversationSessions.mockResolvedValue([readOnly]);
    state.api.conversationSession.mockResolvedValue(readOnly);
    renderChats();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Read-only history",
      }),
    );
    const send = await screen.findByRole("button", {
      name: "This Public Team Chat is read-only.",
    });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    expect(send.getAttribute("title")).toBeNull();
    expect(send.getAttribute("data-ui-guide")).toBe("chat.readOnly");
    expect(send.getAttribute("data-ui-guide-text")).toBe(
      "This Public Team Chat is read-only.",
    );
    expect(screen.queryByRole("button", { name: "Public" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Private" })).toBeNull();
    expect(state.api.streamTeamConversation).not.toHaveBeenCalled();
  });

  it("opens a direct New URL without fetching or selecting historical Chat sessions", async () => {
    window.history.replaceState(null, "", "/student/chat?mode=new");
    renderChats();
    await screen.findByRole("button", { name: /Socrates/ });
    await waitFor(() => expect(state.api.chatAgents).toHaveBeenCalledTimes(1));
    expect(state.api.conversationSessions).not.toHaveBeenCalled();
    expect(state.api.conversations).not.toHaveBeenCalled();
    expect(state.api.conversation).not.toHaveBeenCalled();
    expect(state.api.conversationSession).not.toHaveBeenCalled();
    expect(state.api.createConversation).not.toHaveBeenCalled();
    expect(state.api.createTeamConversation).not.toHaveBeenCalled();
    expect(state.api.streamConversation).not.toHaveBeenCalled();
    expect(state.api.streamTeamConversation).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    expect(sidebarButton("Done").disabled).toBe(true);
  });

  it("refreshes the selected Team history and renders an assistant-only Knowledge notice", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    const originalTurn = {
      id: "team-turn-original",
      user_text: "Old Team question",
      state: "ready",
      member_results: [
        {
          id: "team-result-original",
          participant_id: "participant-1",
          speaker_name: "Bowen",
          assistant_text: "Old Team answer",
          state: "ready",
          safe_error_code: null,
        },
      ],
    };
    const oldTeamSession = {
      ...teamSession,
      revision: 1,
      turns: [originalTurn],
    };
    const noticeTeamSession = {
      ...oldTeamSession,
      revision: 2,
      turns: [
        originalTurn,
        {
          id: "team-turn-knowledge-notice",
          user_text: "",
          state: "ready",
          member_results: [
            {
              id: "team-result-knowledge-notice",
              participant_id: "participant-1",
              speaker_name: "Bowen",
              assistant_text:
                "Your teacher updated this Team's Knowledge. Please answer again.",
              state: "ready",
              safe_error_code: null,
            },
          ],
        },
      ],
    };
    state.api.conversationSessions.mockResolvedValue([oldTeamSession]);
    state.api.conversationSession
      .mockResolvedValueOnce(oldTeamSession)
      .mockResolvedValue(noticeTeamSession);
    renderChats();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Old Team question",
      }),
    );
    await screen.findByText("Old Team answer");
    expect(state.api.conversationSession).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    const notice = await screen.findByText(
      "Your teacher updated this Team's Knowledge. Please answer again.",
    );
    const log = screen.getByRole("log");
    expect(notice.closest('[class*="teamResult"]')).toBeTruthy();
    expect(log.querySelectorAll('[class*="exchange"]')).toHaveLength(2);
    expect(log.querySelectorAll('[class*="userMessage"]')).toHaveLength(1);
    expect(state.api.conversationSession).toHaveBeenCalledTimes(2);
    expect(state.api.conversation).not.toHaveBeenCalled();
    expect(state.api.createTeamConversation).not.toHaveBeenCalled();
    expect(state.api.streamTeamConversation).not.toHaveBeenCalled();
  });

  it("discards a late Team refresh after New opens and stops reading history", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    const originalTurn = {
      id: "team-turn-before-new",
      user_text: "Team question before New",
      state: "ready",
      member_results: [
        {
          id: "team-result-before-new",
          participant_id: "participant-1",
          speaker_name: "Bowen",
          assistant_text: "Team answer before New",
          state: "ready",
          safe_error_code: null,
        },
      ],
    };
    const oldTeamSession = {
      ...teamSession,
      revision: 1,
      turns: [originalTurn],
    };
    const lateTeamSession = {
      ...oldTeamSession,
      revision: 2,
      turns: [
        originalTurn,
        {
          id: "team-turn-after-new",
          user_text: "",
          state: "ready",
          member_results: [
            {
              id: "team-result-after-new",
              participant_id: "participant-1",
              speaker_name: "Bowen",
              assistant_text: "Late notice from the Team Chat.",
              state: "ready",
              safe_error_code: null,
            },
          ],
        },
      ],
    };
    let resolveRefresh!: (value: typeof lateTeamSession) => void;
    const pendingRefresh = new Promise<typeof lateTeamSession>((resolve) => {
      resolveRefresh = resolve;
    });
    state.api.conversationSessions.mockResolvedValue([oldTeamSession]);
    state.api.conversationSession
      .mockResolvedValueOnce(oldTeamSession)
      .mockImplementationOnce(() => pendingRefresh);
    renderChats();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Team question before New",
      }),
    );
    await screen.findByText("Team answer before New");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(state.api.conversationSession).toHaveBeenCalledTimes(2);

    await openNewChat();
    await waitFor(() =>
      expect(screen.queryByText("Team answer before New")).toBeNull(),
    );
    await act(async () => resolveRefresh(lateTeamSession));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });

    expect(screen.queryByText("Late notice from the Team Chat.")).toBeNull();
    expect(state.api.conversationSession).toHaveBeenCalledTimes(2);
    expect(state.api.createTeamConversation).not.toHaveBeenCalled();
    expect(state.api.streamTeamConversation).not.toHaveBeenCalled();
  });

  it("does not let an old directory response appear after an identity switch", async () => {
    let resolveOldDirectory!: (result: (typeof mayaTeam)[]) => void;
    state.api.mayaTeams.mockReturnValue(
      new Promise((resolve) => {
        resolveOldDirectory = resolve;
      }),
    );
    const view = renderChats();
    await openNewChat();
    await waitFor(() => expect(state.api.mayaTeams).toHaveBeenCalled());

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

    await screen.findByText("No chats yet.");
    await openNewChat();
    expect(
      await screen.findByRole("button", {
        name: /Other actor directory item/,
      }),
    ).toBeTruthy();
    await act(async () => resolveOldDirectory([mayaTeam]));

    expect(
      screen.getByRole("button", { name: /Other actor directory item/ }),
    ).toBeTruthy();
    expect(screen.queryByText("Course Dialogue Team")).toBeNull();
  });

  it("routes typed @ recipients by frozen participant IDs and keeps pasted code mentions as plain text", async () => {
    renderChats();
    await startMayaTeamChat("Start the Team Chat");
    await waitFor(() =>
      expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(1),
    );
    const message = await screen.findByRole("textbox", { name: "Message" });
    await waitFor(() =>
      expect((message as HTMLTextAreaElement).value).toBe(""),
    );
    expect(screen.queryByRole("button", { name: "Remove All" })).toBeNull();

    fireEvent.keyDown(message, { key: "@", shiftKey: true });
    const menu = screen.getByRole("menu", { name: "Recipients" });
    expect(
      screen.queryByText(
        "Members with the same name are identified by their role and order.",
      ),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Add @ recipient" }),
    ).toBeNull();
    expect(within(menu).getByRole("menuitem", { name: "All" })).toBeTruthy();
    expect(
      within(menu).getAllByRole("menuitem", { name: "Bowen" }),
    ).toHaveLength(2);
    expect(within(menu).getByRole("menuitem", { name: "Jade" })).toBeTruthy();
    fireEvent.click(within(menu).getByRole("menuitem", { name: "All" }));
    expect(screen.queryByRole("menu", { name: "Recipients" })).toBeNull();
    expect((message as HTMLTextAreaElement).value).toBe("@All");
    expect(screen.queryByRole("button", { name: "Remove All" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Bowen" })).toBeNull();

    fireEvent.change(message, { target: { value: "@" } });
    fireEvent.keyDown(message, { key: "@", shiftKey: true });
    fireEvent.click(
      within(screen.getByRole("menu", { name: "Recipients" })).getAllByRole(
        "menuitem",
        { name: "Bowen" },
      )[0],
    );
    expect((message as HTMLTextAreaElement).value).toBe("@Bowen");
    expect(screen.queryByRole("menu", { name: "Recipients" })).toBeNull();

    const pastedText = "```txt\n@All members @Bowen\n``` this is quoted text";
    fireEvent.change(message, { target: { value: pastedText } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(2),
    );
    expect(state.api.createTeamConversation).toHaveBeenCalledTimes(1);
    expect(state.api.streamTeamConversation.mock.calls[1][0]).toBe(
      "conversation-team-1",
    );
    expect(state.api.streamTeamConversation.mock.calls[1][1]).toMatchObject({
      message: pastedText,
      routing: {
        mode: "selected",
        participant_ids: ["participant-1"],
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
    await startMayaTeamChat("Compare these views");

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

  it.each([
    [
      "student",
      "A Team member could not reply because the current Team data-use authorization needs Teacher confirmation. Ask a Teacher to review and confirm it, then explicitly send a new message.",
    ],
    [
      "teacher",
      "A Team member could not reply because the current Team data-use authorization needs confirmation. Review and confirm it, then explicitly send a new message.",
    ],
  ] as const)(
    "explains a provider confirmation failure safely to a %s without retrying",
    async (role, expectedGuidance) => {
      state.role = role;
      state.api.streamTeamConversation.mockResolvedValueOnce({
        ...teamSession,
        revision: 1,
        turns: [
          {
            id: "provider-confirmation-turn",
            user_text: "Compare the two approaches",
            assistant_text: null,
            mode: "real" as const,
            state: "partial" as const,
            sources: [],
            safe_error_code: null,
            routing: { mode: "all" as const, participant_ids: [] },
            member_results: [
              {
                id: "provider-confirmation-result",
                participant_id: "participant-1",
                speaker_name: "Bowen",
                ordinal: 0,
                state: "failed" as const,
                assistant_text: null,
                sources: [],
                safe_error_code: "provider_confirmation_required",
              },
            ],
          },
        ],
      });

      renderChats();
      await startMayaTeamChat("Compare the two approaches");

      expect(await screen.findByText(expectedGuidance)).toBeTruthy();
      expect(screen.queryByText("provider_confirmation_required")).toBeNull();
      expect(
        screen.queryByText(
          "Team Chat sending is unavailable in the current runtime.",
        ),
      ).toBeNull();
      expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(1);
    },
  );

  it("does not send Enter during Chinese IME composition", async () => {
    renderChats();
    await chooseTarget(/Course Dialogue Team/);
    const message = await screen.findByRole("textbox", { name: "Message" });
    fireEvent.change(message, { target: { value: "你好" } });

    fireEvent.keyDown(message, { key: "Enter", isComposing: true });
    expect(state.api.streamTeamConversation).not.toHaveBeenCalled();
    fireEvent.keyDown(message, { key: "Enter", isComposing: false });
    await waitFor(() =>
      expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(1),
    );
    expect(state.api.createTeamConversation).toHaveBeenCalledTimes(1);
    expect(state.api.streamTeamConversation.mock.calls[0][1].message).toBe(
      "你好",
    );
  });

  it("does not resend an unknown Team request when the user checks its status", async () => {
    state.api.streamTeamConversation.mockRejectedValueOnce(
      new Error("connection reset"),
    );
    renderChats();
    await startMayaTeamChat("Do not duplicate this turn");

    await screen.findByRole("button", { name: "Check Team Chat status" });
    expect(state.api.createTeamConversation).toHaveBeenCalledTimes(1);
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
    expect(
      screen.getAllByText(/you can continue with a new message/i).length,
    ).toBeGreaterThan(0);

    const nextMessage = "Continue with a new message";
    state.api.streamTeamConversation.mockImplementationOnce(
      (_conversationId: string, request: { request_id: string }) =>
        Promise.resolve({
          ...teamSession,
          revision: 2,
          turns: [
            {
              id: requestId,
              user_text: "Do not duplicate this turn",
              assistant_text: null,
              mode: "mock" as const,
              state: "acceptance_unknown" as const,
              sources: [],
              safe_error_code: "chat_acceptance_unknown",
              routing: { mode: "all" as const, participant_ids: [] },
              member_results: [],
            },
            {
              id: request.request_id,
              user_text: nextMessage,
              assistant_text: null,
              mode: "mock" as const,
              state: "ready" as const,
              sources: [],
              safe_error_code: null,
              routing: { mode: "all" as const, participant_ids: [] },
              member_results: [
                {
                  id: "reply-after-unknown",
                  participant_id: "participant-1",
                  speaker_name: "Bowen",
                  ordinal: 0,
                  state: "ready" as const,
                  assistant_text: "A new message received a reply.",
                  sources: [],
                  safe_error_code: null,
                },
              ],
            },
          ],
        }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: nextMessage },
    });
    expect(
      (screen.getByRole("button", { name: "Send" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(
      await screen.findByText("A new message received a reply."),
    ).toBeTruthy();
    expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(2);
    expect(state.api.createTeamConversation).toHaveBeenCalledTimes(1);
    expect(state.api.streamTeamConversation.mock.calls[1][1].message).toBe(
      nextMessage,
    );
    expect(
      state.api.streamTeamConversation.mock.calls[1][1].request_id,
    ).not.toBe(requestId);
    expect(
      screen.getAllByText(/you can continue with a new message/i).length,
    ).toBeGreaterThan(0);
  });
});
