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
import { PlatformApiError } from "../lib/api/platform";

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
    await screen.findByText("No Teams yet.");
    expect(screen.queryByLabelText("Name")).toBeNull();
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
    await screen.findByLabelText("Name");
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
    expect(await screen.findByText("No Teams yet.")).toBeTruthy();
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
    fireEvent.click(
      await screen.findByRole("button", { name: "Reasoning circle" }),
    );

    const name = await screen.findByLabelText("Name");
    expect(navigation.push).toHaveBeenCalledWith(
      "/teacher/chat?mode=team-edit&team_id=team-1",
      { scroll: false },
    );
    // Like Agent Done: unchanged edits keep Done off so a no-op save cannot
    // mint the next Team version.
    expect(sidebarButton("Done").disabled).toBe(true);
    fireEvent.change(name, { target: { value: "Reasoning circle v2" } });
    expect(sidebarButton("Done").disabled).toBe(false);
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

  it("saves a Team with the current version of a member published again", async () => {
    // Socrates was published again as version-1b after the Team was saved.
    state.api.teams.mockResolvedValue([publicTeam]);
    state.api.team.mockResolvedValue(publicTeam);
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeamEntryFlow
            api={state.api as never}
            courseId="course"
            agents={
              [{ ...agents[0], version_id: "version-1b" }, agents[1]] as never
            }
            standalone
            backHref="/teacher/studyform"
            initialRouteMode="teams"
          />
        </AppShell>
      </LocaleProvider>,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Reasoning circle" }),
    );
    const name = await screen.findByLabelText("Name");
    expect(sidebarButton("Done").disabled).toBe(true);
    fireEvent.change(name, { target: { value: "Reasoning circle updated" } });
    fireEvent.click(sidebarButton("Done"));

    await screen.findByText("Team saved. You can now start a Team Chat.");
    expect(state.api.updateTeam.mock.calls[0][1].members).toEqual([
      { agent_version_id: "version-1b", is_leader: true, position: 0 },
      { agent_version_id: "version-2", is_leader: false, position: 1 },
    ]);
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
    await screen.findByLabelText("Name");
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
    await screen.findByLabelText("Name");
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
    expect(screen.queryByText("V1.0")).toBeNull();
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

  it("shows a visiting teacher the group's Teams read-only, without creating one", async () => {
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
    // The group's Teams are listed for the teacher to look at, asked for by
    // group so its members' private Teams come too.
    expect(screen.getByRole("heading", { name: "Teams" })).toBeTruthy();
    expect(state.api.teams).toHaveBeenCalledWith("course", "group-1");
    // But a visit never starts one: no form, and no New.
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

  it("keeps the Chat Done created when the router later drops mode=new", async () => {
    state.api.teams.mockResolvedValue([
      { ...team, can_edit: false, visibility: "public" },
    ]);
    const view = renderChats();
    // A real router shows each push only after the page has rendered it.
    const showUrl = (url: string) =>
      act(() => {
        window.history.pushState(null, "", url);
        view.rerender(
          <LocaleProvider initialLocale="en">
            <UiGuideTooltip />
            <AppShell role="student">
              <AgentChat />
            </AppShell>
          </LocaleProvider>,
        );
      });
    await openNewChat();
    showUrl("/student/chat?mode=new");
    fireEvent.click(
      await screen.findByRole("button", { name: /Reasoning circle/ }),
    );
    const done = sidebarButton("Done");
    await waitFor(() => expect(done.disabled).toBe(false));
    fireEvent.click(done);
    await screen.findByRole("textbox", { name: "Message" });
    const historyReads = state.api.conversationSessions.mock.calls.length;

    showUrl("/student/chat");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    expect(screen.getByRole("textbox", { name: "Message" })).toBeTruthy();
    expect(screen.getByText("Team")).toBeTruthy();
    expect(state.api.conversationSessions).toHaveBeenCalledTimes(historyReads);
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
      routing: { mode: "all", participant_ids: [] },
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
    await screen.findByLabelText("Name");
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

  it("explains under the latest message that a member Agent was deleted", async () => {
    const history = {
      ...teamSession,
      can_send: false,
      team: {
        ...teamSession.team,
        available: false,
        members: teamSession.team.members.map((member, index) =>
          index === 1 ? { ...member, available: false, deleted: true } : member,
        ),
      },
      turns: [
        {
          id: "kept-turn",
          user_text: "A kept Team question",
          state: "ready",
          member_results: [],
        },
      ],
    };
    state.api.conversationSessions.mockResolvedValue([history]);
    state.api.conversationSession.mockResolvedValue(history);
    renderChats();
    fireEvent.click(
      await screen.findByRole("button", { name: "A kept Team question" }),
    );
    const log = await screen.findByRole("log");
    const deletedName = teamSession.team.members[1].name;
    expect(
      await within(log).findByText(
        `${deletedName} was deleted by its publisher. This Team chat can't continue; its history is kept.`,
      ),
    ).toBeTruthy();
    expect(within(log).getByText("A kept Team question")).toBeTruthy();
    expect(
      screen.queryByText(
        "Team Chat sending is unavailable in the current runtime.",
      ),
    ).toBeNull();
  });

  it("says the members are unavailable, not the runtime, when none can be reached", async () => {
    const history = {
      ...teamSession,
      can_send: false,
      team: {
        ...teamSession.team,
        available: false,
        members: teamSession.team.members.map((member) => ({
          ...member,
          available: false,
        })),
      },
      turns: [
        {
          id: "closed-turn",
          user_text: "A closed Team question",
          state: "ready",
          member_results: [],
        },
      ],
    };
    state.api.conversationSessions.mockResolvedValue([history]);
    state.api.conversationSession.mockResolvedValue(history);
    renderChats();
    fireEvent.click(
      await screen.findByRole("button", { name: "A closed Team question" }),
    );
    const log = await screen.findByRole("log");
    expect(
      await within(log).findByText(
        "This Team Chat can't continue: its members are no longer available to you. Start a new Chat with the Team.",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText(
        "Team Chat sending is unavailable in the current runtime.",
      ),
    ).toBeNull();
  });

  it("tells the student an unrecorded answer must be sent again", async () => {
    state.api.streamTeamConversation.mockResolvedValue({
      ...teamSession,
      revision: 1,
      turns: [
        {
          id: "answer-turn",
          user_text: "My answer",
          state: "failed",
          member_results: [
            {
              id: "leader-result",
              participant_id: "participant-1",
              speaker_name: "Bowen",
              ordinal: 0,
              state: "failed",
              assistant_text: null,
              sources: [],
              safe_error_code: "assessment_action_required",
            },
          ],
        },
      ],
    });
    renderChats();
    await startMayaTeamChat("My answer");
    expect(
      await screen.findByText(
        "Your answer was not recorded. Send it again to continue the assessment.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("This Team member could not reply.")).toBeNull();
  });

  it("ends a finished test at the summary progress bar", async () => {
    const finished = {
      ...teamSession,
      assessment_stage: "summarizing" as const,
      can_send: true,
      turns: [
        {
          id: "q1",
          user_text: "B",
          state: "ready" as const,
          member_results: [
            {
              id: "recorded",
              participant_id: "participant-1",
              speaker_name: "Scorer",
              ordinal: 0,
              state: "ready" as const,
              assistant_text: "已记录你的回答。",
              sources: [],
              safe_error_code: null,
            },
            {
              id: "next",
              participant_id: "participant-3",
              speaker_name: "Guider",
              ordinal: 1,
              state: "ready" as const,
              assistant_text: "第 2 题：下一题",
              sources: [],
              safe_error_code: null,
            },
          ],
        },
        {
          id: "last",
          user_text: "4",
          state: "ready" as const,
          member_results: [
            {
              id: "recorded-last",
              participant_id: "participant-1",
              speaker_name: "Scorer",
              ordinal: 0,
              state: "ready" as const,
              assistant_text: "已记录你的回答。",
              sources: [],
              safe_error_code: null,
            },
            {
              id: "done",
              participant_id: "participant-3",
              speaker_name: "Guider",
              ordinal: 1,
              state: "ready" as const,
              assistant_text: "答题全部结束",
              sources: [],
              safe_error_code: null,
            },
            {
              id: "summary",
              participant_id: "participant-2",
              speaker_name: "Summarizer",
              ordinal: 2,
              state: "ready" as const,
              assistant_text: "正在总结答案",
              sources: [],
              safe_error_code: null,
            },
          ],
        },
        {
          id: "score-turn",
          user_text: "",
          state: "ready" as const,
          member_results: [
            {
              id: "reviewed",
              participant_id: "participant-1",
              speaker_name: "Scorer",
              ordinal: 0,
              state: "ready" as const,
              assistant_text: "本轮回答已评估。",
              sources: [],
              safe_error_code: null,
            },
          ],
        },
        {
          id: "save-turn",
          user_text: "",
          state: "partial" as const,
          member_results: [
            {
              id: "save-failed",
              participant_id: "participant-2",
              speaker_name: "Summarizer",
              ordinal: 0,
              state: "failed" as const,
              assistant_text: null,
              sources: [],
              safe_error_code: "assessment_executor_write_required",
            },
          ],
        },
      ],
    };
    state.api.conversationSessions.mockResolvedValue([finished]);
    state.api.conversationSession.mockResolvedValue(finished);
    renderChats();
    fireEvent.click(await screen.findByRole("button", { name: "B" }));
    const log = await screen.findByRole("log");
    const cards = [
      ...log.querySelectorAll<HTMLElement>('article[class*="teamResult"]'),
    ];
    const visible = cards.map((card) => card.textContent ?? "");
    expect(visible).toHaveLength(4);
    expect(visible[0]).toContain("已记录你的回答。");
    expect(visible[1]).toContain("第 2 题：下一题");
    expect(visible[2]).toContain("答题全部结束");
    expect(visible[3]).toContain("正在总结答案");
    expect(
      visible.filter((text) => text.includes("已记录你的回答。")),
    ).toHaveLength(1);
    expect(
      within(cards[3]).getByRole("progressbar", {
        name: "Test progress",
      }),
    ).toBeTruthy();
    expect(within(log).getAllByRole("progressbar")).toHaveLength(1);
    expect(log.textContent).not.toContain("本轮回答已评估。");
    expect(log.textContent).not.toContain(
      "Some members could not reply. Successful replies are kept.",
    );
    expect(log.textContent).not.toContain(
      "This Team member could not save the summary. Send a new message to try again.",
    );
    expect(
      (screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement)
        .disabled,
    ).toBe(false);
  });

  it.each([
    [
      503,
      "adaptive_admission_busy",
      "Many people are using Maya right now. Press Send again in a moment.",
    ],
    [
      409,
      "chat_busy",
      "The previous message is still being answered. Send again in a moment.",
    ],
  ])(
    "keeps a refused Team message (%s %s) in the box without resending it",
    async (status, code, hint) => {
      state.api.streamTeamConversation.mockRejectedValue(
        new PlatformApiError(status, "busy", { code, message: "busy" }),
      );
      renderChats();
      await startMayaTeamChat("我的答案是 B");
      expect(await screen.findByText(hint)).toBeTruthy();
      const box = screen.getByRole("textbox", {
        name: "Message",
      }) as HTMLTextAreaElement;
      expect(box.value).toBe("我的答案是 B");
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(1);
      const send = screen.getByRole("button", { name: "Send" });
      expect(send.hasAttribute("disabled")).toBe(false);
      fireEvent.click(send);
      await waitFor(() =>
        expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(2),
      );
      expect(state.api.streamTeamConversation.mock.calls[1][1]).toMatchObject({
        message: "我的答案是 B",
      });
    },
  );

  it("disables Send while a Team message is in flight", async () => {
    state.api.streamTeamConversation.mockImplementation(
      () => new Promise(() => {}),
    );
    renderChats();
    await startMayaTeamChat("只发一次");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Send" }).hasAttribute("disabled"),
      ).toBe(true),
    );
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(1);
  });

  it("shows a sent Team message at once with its loading state", async () => {
    state.api.streamTeamConversation.mockImplementation(
      () => new Promise(() => {}),
    );
    renderChats();
    await startMayaTeamChat("还在等回复");

    const log = await screen.findByRole("log");
    expect(await within(log).findByText("还在等回复")).toBeTruthy();
    expect(within(log).getByRole("status").textContent).toContain("Loading");
    const box = screen.getByRole("textbox", {
      name: "Message",
    }) as HTMLTextAreaElement;
    expect(box.value).toBe("");
  });

  it("shows the progress bar as soon as the last answer's reply arrives", async () => {
    state.api.streamTeamConversation.mockImplementation(
      async (_id: string, body: { request_id: string; message: string }) => ({
        ...teamSession,
        assessment_stage: "scoring",
        // The server's scoring turn runs, so sending is closed for now.
        can_send: false,
        turns: [
          {
            id: body.request_id,
            user_text: body.message,
            state: "ready",
            member_results: [],
          },
        ],
      }),
    );
    renderChats();
    await startMayaTeamChat("I don't know");
    const bar = await screen.findByRole("progressbar", {
      name: "Test progress",
    });
    expect(bar.getAttribute("aria-valuenow")).toBe("40");
    expect(
      screen.queryByText(
        "Team Chat sending is unavailable in the current runtime.",
      ),
    ).toBeNull();
  });

  it("keeps formal micro-round order and hangs the bar on the summarizer line", async () => {
    const finished = {
      ...teamSession,
      assessment_stage: "scoring" as const,
      can_send: false,
      turns: [
        {
          id: "micro",
          user_text: "乙",
          state: "ready" as const,
          member_results: [
            {
              id: "scorer",
              participant_id: "participant-1",
              speaker_name: "Bowen",
              ordinal: 1,
              state: "ready" as const,
              assistant_text: "已记录你的回答。",
              sources: [],
              safe_error_code: null,
            },
            {
              id: "guide",
              participant_id: "participant-3",
              speaker_name: "Jade",
              ordinal: 0,
              state: "ready" as const,
              assistant_text: "答题全部结束",
              sources: [],
              safe_error_code: null,
            },
            {
              id: "summarizer",
              participant_id: "participant-2",
              speaker_name: "Kaikai",
              ordinal: 2,
              state: "ready" as const,
              assistant_text: "正在总结答案",
              sources: [],
              safe_error_code: null,
            },
          ],
        },
      ],
    };
    state.api.conversationSessions.mockResolvedValue([finished]);
    state.api.conversationSession.mockResolvedValue(finished);
    renderChats();
    fireEvent.click(await screen.findByRole("button", { name: "乙" }));
    const log = await screen.findByRole("log");
    const headings = within(log)
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent);
    expect(headings).toEqual(["Jade", "Kaikai"]);
    expect(log.textContent).not.toContain("已记录你的回答。");
    const articles = within(log).getAllByRole("article");
    const summarizer = articles.find((article) =>
      article.textContent?.includes("正在总结答案"),
    );
    expect(summarizer).toBeTruthy();
    expect(
      within(summarizer as HTMLElement).getByRole("progressbar", {
        name: "Test progress",
      }),
    ).toBeTruthy();
    expect(within(log).getAllByRole("progressbar")).toHaveLength(1);
  });

  it("shows the formal test progress and checks until scoring finishes", async () => {
    const scoring = {
      ...teamSession,
      assessment_stage: "scoring",
      turns: [
        {
          id: "last-answer",
          user_text: "B",
          state: "ready",
          member_results: [],
        },
      ],
    };
    const finished = { ...scoring, assessment_stage: "completed" };
    state.api.conversationSessions.mockResolvedValue([scoring]);
    state.api.conversationSession
      .mockResolvedValueOnce(scoring)
      .mockResolvedValue(finished);
    renderChats();
    fireEvent.click(await screen.findByRole("button", { name: "B" }));
    const bar = await screen.findByRole("progressbar", {
      name: "Test progress",
    });
    expect(bar.getAttribute("aria-valuenow")).toBe("40");
    expect(screen.getByText("Answers saved · scoring · 40%")).toBeTruthy();
    await waitFor(
      () =>
        expect(
          screen.getByRole("progressbar").getAttribute("aria-valuenow"),
        ).toBe("100"),
      { timeout: 4000 },
    );
    expect(
      screen.getByText("Scoring finished · the test is complete · 100%"),
    ).toBeTruthy();
  });

  // Bug (2026-10-13): while the server picked the follow-ups the student
  // could type, and the answer landed before the follow-up appeared.
  it("keeps the message box closed while follow-ups are prepared, with no bar", async () => {
    const preparing = {
      ...teamSession,
      assessment_stage: "preparing",
      turns: [
        {
          id: "last-answer",
          user_text: "a",
          state: "ready",
          member_results: [],
        },
      ],
    };
    state.api.conversationSessions.mockResolvedValue([preparing]);
    state.api.conversationSession.mockResolvedValue(preparing);
    renderChats();
    fireEvent.click(await screen.findByRole("button", { name: "a" }));
    const box = (await screen.findByRole("textbox", {
      name: "Message",
    })) as HTMLTextAreaElement;
    await waitFor(() => expect(box.disabled).toBe(true));
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("opens a Team Chat at its newest message", async () => {
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    const history = {
      ...teamSession,
      turns: [
        { id: "old", user_text: "First", state: "ready", member_results: [] },
        { id: "new", user_text: "Latest", state: "ready", member_results: [] },
      ],
    };
    state.api.conversationSessions.mockResolvedValue([history]);
    state.api.conversationSession.mockResolvedValue(history);
    renderChats();
    fireEvent.click(await screen.findByRole("button", { name: "First" }));
    await within(await screen.findByRole("log")).findByText("Latest");
    await waitFor(() => expect(scrolled).toHaveBeenCalled());
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
    expect(within(menu).queryByRole("menuitem", { name: "All" })).toBeNull();
    expect(
      within(menu).getAllByRole("menuitem", { name: "Bowen" }),
    ).toHaveLength(2);
    expect(within(menu).getByRole("menuitem", { name: "Jade" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Remove All" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Bowen" })).toBeNull();

    fireEvent.click(
      within(menu).getAllByRole("menuitem", { name: "Bowen" })[0],
    );
    expect(screen.queryByRole("menu", { name: "Recipients" })).toBeNull();
    expect((message as HTMLTextAreaElement).value).toBe("@Bowen ");
    expect((message as HTMLTextAreaElement).selectionStart).toBe(
      "@Bowen ".length,
    );
    expect((message as HTMLTextAreaElement).selectionEnd).toBe(
      "@Bowen ".length,
    );

    fireEvent.change(message, { target: { value: "@" } });
    fireEvent.keyDown(message, { key: "@", shiftKey: true });
    fireEvent.click(
      within(screen.getByRole("menu", { name: "Recipients" })).getAllByRole(
        "menuitem",
        { name: "Jade" },
      )[0],
    );
    expect((message as HTMLTextAreaElement).value).toBe("@Jade ");
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
      // Mentions inside fenced code are ignored; bare default is all members.
      routing: {
        mode: "all",
        participant_ids: [],
      },
    });
  });

  it("Backspace after a picked @Name drops the name, keeps @ and reopens the picker; wrong @ falls back to all", async () => {
    renderChats();
    await startMayaTeamChat("Start the Team Chat");
    await waitFor(() =>
      expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(1),
    );
    const message = (await screen.findByRole("textbox", {
      name: "Message",
    })) as HTMLTextAreaElement;
    await waitFor(() => expect(message.value).toBe(""));

    fireEvent.change(message, { target: { value: "hi @" } });
    fireEvent.keyDown(message, { key: "@", shiftKey: true });
    fireEvent.click(
      within(screen.getByRole("menu", { name: "Recipients" })).getByRole(
        "menuitem",
        { name: "Jade" },
      ),
    );
    expect(message.value).toBe("hi @Jade ");
    expect(message.selectionStart).toBe("hi @Jade ".length);

    fireEvent.keyDown(message, { key: "Backspace" });
    expect(message.value).toBe("hi @");
    expect(message.selectionStart).toBe("hi @".length);
    expect(screen.getByRole("menu", { name: "Recipients" })).toBeTruthy();

    // Ordinary typed text is not collapsed (default Backspace handling).
    fireEvent.keyDown(message, { key: "Escape" });
    fireEvent.change(message, { target: { value: "plain text " } });
    message.setSelectionRange(11, 11);
    fireEvent.keyDown(message, { key: "Backspace" });
    expect(message.value).toBe("plain text ");
    expect(screen.queryByRole("menu", { name: "Recipients" })).toBeNull();

    fireEvent.change(message, { target: { value: "@Nobody 你好" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(state.api.streamTeamConversation).toHaveBeenCalledTimes(2),
    );
    expect(state.api.streamTeamConversation.mock.calls[1][1]).toMatchObject({
      routing: { mode: "all", participant_ids: [] },
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

  it("omits a silent member instead of a could-not-reply card", async () => {
    const silentSession = {
      ...teamSession,
      revision: 2,
      turns: [
        {
          id: "silent-turn",
          user_text: "我答的怎么样",
          assistant_text: null,
          mode: "mock" as const,
          state: "partial" as const,
          sources: [],
          safe_error_code: "team_partial_failure",
          routing: { mode: "all" as const, participant_ids: [] },
          member_results: [
            {
              id: "score",
              participant_id: "participant-1",
              speaker_name: "Scorer",
              ordinal: 0,
              state: "ready" as const,
              assistant_text: "第 1 题得 1 分，正确选项是 A。",
              sources: [],
              safe_error_code: null,
            },
            {
              id: "silent-invalid",
              participant_id: "participant-2",
              speaker_name: "Summarizer",
              ordinal: 1,
              state: "failed" as const,
              assistant_text: null,
              sources: [],
              safe_error_code: "team_response_invalid",
            },
            {
              id: "silent-mark",
              participant_id: "participant-3",
              speaker_name: "Guider",
              ordinal: 2,
              state: "ready" as const,
              assistant_text: "\u2060",
              sources: [],
              safe_error_code: null,
            },
          ],
        },
      ],
    };
    state.api.conversationSessions.mockResolvedValue([silentSession]);
    state.api.conversationSession.mockResolvedValue(silentSession);
    render(
      <LocaleProvider initialLocale="zh">
        <UiGuideTooltip />
        <AppShell role="student">
          <AgentChat />
        </AppShell>
      </LocaleProvider>,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "我答的怎么样" }),
    );
    const log = await screen.findByRole("log");
    expect(within(log).getByText(/正确选项是 A/)).toBeTruthy();
    expect(within(log).queryByText("这位 Team 成员未能回复。")).toBeNull();
    expect(
      within(log).queryByText("部分成员未能回复；已成功的回复已保留。"),
    ).toBeNull();
    expect(
      within(log).queryByText("This Team member could not reply."),
    ).toBeNull();
    expect(within(log).getAllByRole("heading")).toHaveLength(1);
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

  it("sends only from the Send button, never from Enter", async () => {
    renderChats();
    await chooseTarget(/Course Dialogue Team/);
    const message = await screen.findByRole("textbox", { name: "Message" });
    fireEvent.change(message, { target: { value: "你好" } });

    fireEvent.keyDown(message, { key: "Enter", isComposing: true });
    fireEvent.keyDown(message, { key: "Enter", isComposing: false });
    expect(state.api.streamTeamConversation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
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
