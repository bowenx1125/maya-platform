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

import type { AgentDetail, AgentVersion } from "../lib/api";
import { AppShell } from "../components/app-shell";
import { AgentOverview } from "../components/agent-workspace";
import { GroupWorkspace } from "../components/student-workspace";
import { TeacherAgentDetail } from "../components/teacher-workspace";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/student/agents/agent-id",
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({ api }),
}));

function version(overrides: Partial<AgentVersion> = {}): AgentVersion {
  return {
    id: "published-id",
    agent_id: "agent-id",
    version_label: "V1.0",
    state: "published",
    revision: 0,
    agent_md: "# Current prompt",
    avatar_config: null,
    voice_fallback_active: true,
    enabled_documents: [],
    publish_blockers: [],
    ...overrides,
  } as AgentVersion;
}

function agent(overrides: Partial<AgentDetail> = {}): AgentDetail {
  return {
    id: "agent-id",
    group_id: "group-id",
    name: "Agent",
    description: "Mutable description",
    status: "active",
    can_edit: true,
    current_published_version_id: "published-id",
    current_draft_version_id: null,
    versions: [],
    ...overrides,
  } as AgentDetail;
}

const api = {
  agent: vi.fn(),
  versions: vi.fn(),
  nextVersion: vi.fn(),
  deleteAgent: vi.fn(),
  group: vi.fn(),
  agents: vi.fn(),
  knowledge: vi.fn(),
  chatAgents: vi.fn().mockResolvedValue([]),
  knowledgeSets: vi.fn().mockResolvedValue([]),
  voiceProfiles: vi.fn(),
  version: vi.fn(),
  ragPreview: vi.fn().mockResolvedValue(null),
  avatarTemplates: vi.fn().mockResolvedValue([]),
  agentKnowledgeSets: vi.fn().mockResolvedValue({
    agent_id: "agent-id",
    agent_metadata_revision: 0,
    sets: [],
  }),
  workspaceDocuments: vi.fn().mockResolvedValue([]),
};

describe("Workspace Agent flow", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.agent.mockResolvedValue(agent());
    api.versions.mockResolvedValue([version()]);
    api.nextVersion.mockResolvedValue(
      version({ id: "draft-id", state: "draft", version_label: "V1.1" }),
    );
    api.chatAgents.mockResolvedValue([]);
    api.knowledgeSets.mockResolvedValue([]);
    api.voiceProfiles.mockResolvedValue([]);
    api.version.mockResolvedValue(
      version({ id: "draft-id", state: "draft", version_label: "V1.1" }),
    );
    api.ragPreview.mockResolvedValue(null);
    api.avatarTemplates.mockResolvedValue([]);
    api.agentKnowledgeSets.mockResolvedValue({
      agent_id: "agent-id",
      agent_metadata_revision: 0,
      sets: [],
    });
    api.workspaceDocuments.mockResolvedValue([]);
    api.knowledge.mockResolvedValue([]);
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("opens the current Check directly, without Info or a version-selection step", async () => {
    api.versions.mockResolvedValue([
      version({ id: "old-id", state: "superseded", agent_md: "# Old prompt" }),
      version(),
    ]);
    api.version.mockResolvedValue(version());
    render(
      <AppShell role="student">
        <AgentOverview agentId="agent-id" />
      </AppShell>,
    );
    expect(
      (
        (await screen.findByRole("textbox", {
          name: "AGENT.md editor",
        })) as HTMLTextAreaElement
      ).value,
    ).toBe("# Current prompt");
    expect(screen.queryByText("Old prompt")).toBeNull();
    expect(screen.queryByText("Mutable description")).toBeNull();
    expect(screen.queryByText("Info")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Versions" })).toBeNull();
    const nav = within(screen.getByRole("navigation"));
    expect(
      (await nav.findByRole("link", { name: "Back" })).getAttribute("href"),
    ).toBe("/student/groups/group-id");
    expect(nav.queryByRole("button", { name: "New" })).toBeNull();
    expect(nav.getByRole("button", { name: "Done" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(api.nextVersion).not.toHaveBeenCalled();
  });

  it("opens a published Agent in the editor and does not save a draft before Done", async () => {
    api.version.mockResolvedValue(version());
    render(
      <AppShell role="student">
        <AgentOverview agentId="agent-id" />
      </AppShell>,
    );
    const nav = within(screen.getByRole("navigation"));
    expect(
      (await nav.findByRole("link", { name: "Back" })).getAttribute("href"),
    ).toBe("/student/groups/group-id");
    expect(nav.queryByRole("button", { name: "New" })).toBeNull();
    expect(api.nextVersion).not.toHaveBeenCalled();
  });

  it("opens a Teacher Agent with Back and uses sidebar New for the next version", async () => {
    api.agent.mockResolvedValue(
      agent({
        ownership_scope: "personal",
        group_id: null,
        current_published_version_id: "published-id",
        current_draft_version_id: null,
      }),
    );
    api.versions.mockResolvedValue([version()]);
    render(
      <AppShell role="teacher">
        <TeacherAgentDetail agentId="agent-id" />
      </AppShell>,
    );

    const navigation = within(screen.getByRole("navigation"));
    await waitFor(() => {
      const backs = navigation.getAllByRole("link", { name: "Back" });
      expect(backs.map((link) => link.getAttribute("href"))).toContain(
        "/teacher/studyform",
      );
    });
    expect(navigation.queryByRole("button", { name: "New" })).toBeNull();
    expect(api.nextVersion).not.toHaveBeenCalled();
    expect(
      await screen.findByRole("textbox", { name: "AGENT.md editor" }),
    ).toBeTruthy();
  });

  it("continues an existing next-version draft without making a second one", async () => {
    api.agent.mockResolvedValue(
      agent({ current_draft_version_id: "draft-id" }),
    );
    api.versions.mockResolvedValue([
      version({ id: "draft-id", state: "draft", agent_md: "# Unsigned draft" }),
      version(),
    ]);
    render(
      <AppShell role="student">
        <AgentOverview agentId="agent-id" />
      </AppShell>,
    );
    expect(
      await screen.findByRole("textbox", { name: "AGENT.md editor" }),
    ).toBeTruthy();
    expect(api.nextVersion).not.toHaveBeenCalled();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("uses page New to edit an initial draft without inline Edit or Delete", async () => {
    api.agent.mockResolvedValue(
      agent({
        current_published_version_id: null,
        current_draft_version_id: "draft-id",
      }),
    );
    api.versions.mockResolvedValue([
      version({ id: "draft-id", state: "draft" }),
    ]);
    render(
      <AppShell role="student">
        <AgentOverview agentId="agent-id" />
      </AppShell>,
    );
    expect(
      await screen.findByRole("textbox", { name: "AGENT.md editor" }),
    ).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(api.nextVersion).not.toHaveBeenCalled();
    expect(api.deleteAgent).not.toHaveBeenCalled();
  });

  it("does not expose deletion for an Agent with a retained published snapshot", async () => {
    api.agent.mockResolvedValue(
      agent({
        current_published_version_id: null,
        current_draft_version_id: "draft-id",
      }),
    );
    api.versions.mockResolvedValue([
      version({
        id: "old-id",
        state: "superseded",
        knowledge_snapshot_id: "snapshot-id",
      }),
      version({ id: "draft-id", state: "draft" }),
    ]);
    render(
      <AppShell role="student">
        <AgentOverview agentId="agent-id" />
      </AppShell>,
    );
    expect(
      await screen.findByRole("textbox", { name: "AGENT.md editor" }),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("navigation")).queryByRole("button", {
        name: "New",
      }),
    ).toBeNull();
    expect(router.replace).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(api.nextVersion).not.toHaveBeenCalled();
  });

  it("opens current Agent inspection from a keyboard-focusable Workspace row", async () => {
    api.group.mockResolvedValue({
      id: "group-id",
      course_id: "course-id",
      name: "Group",
      members: [],
    });
    api.agents.mockResolvedValue([agent()]);
    render(
      <AppShell role="student">
        <GroupWorkspace groupId="group-id" />
      </AppShell>,
    );
    const link = await within(screen.getByRole("main")).findByRole("link", {
      name: /Agent/,
    });
    link.focus();
    expect(document.activeElement).toBe(link);
    expect(link.getAttribute("href")).toBe("/student/agents/agent-id");
    expect(screen.getByRole("heading", { name: "Agents" })).toBeTruthy();
    expect(screen.getByText("V1.0")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Members" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByText("Mutable description")).toBeNull();
    expect(api.knowledge).not.toHaveBeenCalled();
    expect(api.versions).toHaveBeenCalledWith("agent-id");
  });

  it("keeps teacher inspection read-only without the removed description", async () => {
    api.agent.mockResolvedValue(agent({ can_edit: false }));
    render(
      <AppShell role="teacher">
        <TeacherAgentDetail agentId="agent-id" />
      </AppShell>,
    );
    await screen.findByRole("heading", { name: "Current prompt" });
    expect(screen.getByRole("heading", { name: "Avatar" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Brainform" })).toBeTruthy();
    expect(
      screen.queryByRole("textbox", { name: "AGENT.md editor" }),
    ).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByText("Mutable description")).toBeNull();
    const nav = within(screen.getByRole("navigation"));
    expect(nav.queryByRole("button", { name: "New" })).toBeNull();
    expect(nav.queryByRole("button", { name: "Done" })).toBeNull();
    expect(nav.getByRole("link", { name: "Back" })).toBeTruthy();
  });

  it("deletes a Workspace Agent only after confirmation and retains a blocked row", async () => {
    api.group.mockResolvedValue({
      id: "group-id",
      course_id: "course-id",
      name: "Group",
      members: [],
    });
    api.agents.mockResolvedValue([agent()]);
    vi.spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValue(true);
    api.deleteAgent
      .mockRejectedValueOnce(new Error("Used by a Debate"))
      .mockResolvedValue(undefined);
    render(
      <AppShell role="student">
        <GroupWorkspace groupId="group-id" />
      </AppShell>,
    );
    const button = await screen.findByRole("button", { name: "Delete" });
    expect(button.closest("a")).toBeNull();
    fireEvent.click(button);
    expect(api.deleteAgent).not.toHaveBeenCalled();
    fireEvent.click(button);
    await screen.findByText("Used by a Debate");
    expect(
      within(screen.getByRole("main")).getByRole("link", { name: /Agent/ }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(
        within(screen.getByRole("main")).queryByRole("link", { name: /Agent/ }),
      ).toBeNull(),
    );
    expect(api.deleteAgent).toHaveBeenCalledTimes(2);
  });
  it("hides Delete on a groupmate's Agent the viewer can only read or use", async () => {
    api.group.mockResolvedValue({
      id: "group-id",
      course_id: "course-id",
      name: "Group",
      members: [],
    });
    api.agents.mockResolvedValue([
      agent({ id: "mine", name: "Mine", can_edit: true }),
      agent({ id: "shared", name: "Shared", can_edit: false }),
    ]);
    render(
      <AppShell role="student">
        <GroupWorkspace groupId="group-id" />
      </AppShell>,
    );
    await screen.findByRole("link", { name: /Shared/ });
    // Exactly one × — on the viewer's own Agent, none on the shared one.
    const buttons = screen.getAllByRole("button", { name: "Delete" });
    expect(buttons).toHaveLength(1);
    expect(
      buttons[0].closest("[data-agent-row], li, div")?.textContent,
    ).toContain("Mine");
    expect(api.deleteAgent).not.toHaveBeenCalled();
  });
});
