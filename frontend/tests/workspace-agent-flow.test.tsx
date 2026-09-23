import {
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
  updateAgentMetadata: vi.fn(),
};

describe("Workspace Agent flow", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.agent.mockResolvedValue(agent());
    api.versions.mockResolvedValue([version()]);
    api.nextVersion.mockResolvedValue(
      version({ id: "draft-id", state: "draft", version_label: "V1.1" }),
    );
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
    render(
      <AppShell role="student">
        <AgentOverview agentId="agent-id" />
      </AppShell>,
    );
    await screen.findByText("Current prompt");
    expect(screen.queryByText("Old prompt")).toBeNull();
    expect(screen.queryByText("Mutable description")).toBeNull();
    expect(screen.queryByText("Info")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Versions" })).toBeNull();
    const nav = within(screen.getByRole("navigation"));
    expect(
      (await nav.findByRole("link", { name: "Back" })).getAttribute("href"),
    ).toBe("/student/groups/group-id");
    expect(
      within(screen.getByRole("main")).queryByRole("link", { name: "Back" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(api.updateAgentMetadata).not.toHaveBeenCalled();
  });

  it("uses New to create the next version of this Agent", async () => {
    render(
      <AppShell role="student">
        <AgentOverview agentId="agent-id" />
      </AppShell>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "New" }));
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith(
        "/student/agent-versions/draft-id/edit",
      ),
    );
    expect(api.nextVersion).toHaveBeenCalledTimes(1);
    expect(api.nextVersion).toHaveBeenCalledWith("agent-id", {
      idempotency: expect.objectContaining({ key: expect.any(String) }),
    });
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
    const next = await screen.findByRole("link", { name: "New" });
    expect(next.getAttribute("href")).toBe(
      "/student/agent-versions/draft-id/edit",
    );
    expect(screen.getByText("Current prompt")).toBeTruthy();
    expect(screen.queryByText("Unsigned draft")).toBeNull();
    expect(api.nextVersion).not.toHaveBeenCalled();
  });

  it("opens an initial draft for editing and requires confirmation to delete it", async () => {
    api.agent.mockResolvedValue(
      agent({
        current_published_version_id: null,
        current_draft_version_id: "draft-id",
      }),
    );
    api.versions.mockResolvedValue([
      version({ id: "draft-id", state: "draft" }),
    ]);
    api.deleteAgent.mockResolvedValue(undefined);
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    render(
      <AppShell role="student">
        <AgentOverview agentId="agent-id" />
      </AppShell>,
    );
    expect(
      (await screen.findByRole("link", { name: "Edit" })).getAttribute("href"),
    ).toBe("/student/agent-versions/draft-id/edit");
    expect(screen.queryByRole("button", { name: "New" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(api.deleteAgent).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.deleteAgent).toHaveBeenCalledTimes(1));
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(router.replace).toHaveBeenCalledWith("/student/groups/group-id");
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
    await screen.findByRole("link", { name: "Edit" });
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
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
    const link = await screen.findByRole("link", { name: /Agent/ });
    link.focus();
    expect(document.activeElement).toBe(link);
    expect(link.getAttribute("href")).toBe("/student/agents/agent-id");
    expect(screen.getByText("Agents · 1")).toBeTruthy();
    expect(screen.getByText("V1.0")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Members" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByText("Mutable description")).toBeNull();
    expect(api.knowledge).not.toHaveBeenCalled();
    expect(api.updateAgentMetadata).not.toHaveBeenCalled();
    expect(api.versions).toHaveBeenCalledWith("agent-id");
  });

  it("keeps teacher inspection read-only without the removed description", async () => {
    render(
      <AppShell role="teacher">
        <TeacherAgentDetail agentId="agent-id" />
      </AppShell>,
    );
    await screen.findByText("Current prompt");
    expect(screen.queryByText("Mutable description")).toBeNull();
    expect(screen.queryByRole("button", { name: "New" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Done" })).toBeNull();
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
    await screen.findByRole("alert");
    expect(screen.getByRole("link", { name: /Agent/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: /Agent/ })).toBeNull(),
    );
    expect(api.deleteAgent).toHaveBeenCalledTimes(2);
  });
});
