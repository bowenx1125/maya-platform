import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  PlatformApiError,
  type AgentDetail,
  type AgentSummary,
  type AgentVersion,
  type PlatformApi,
} from "../lib/api";
import { LocaleProvider } from "../components/locale";

vi.mock("next/navigation", () => ({
  useRouter: () => router,
}));

vi.mock("../components/session-provider", () => ({
  useSession: vi.fn(),
}));

import { useSession } from "../components/session-provider";
import { AgentOverview } from "../components/agent-workspace";
import { GroupWorkspace } from "../components/student-workspace";
import { TeacherAgentDetail } from "../components/teacher-workspace";

const router = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}));

const agentId = "agent-id";
const groupId = "group-id";
const versionId = "version-id";
const mockedUseSession = vi.mocked(useSession);

function draftAgent(
  description = "",
): AgentDetail & { metadata_revision?: number } {
  return {
    id: agentId,
    group_id: groupId,
    name: "Draft Agent",
    description,
    status: "active",
    current_published_version_id: null,
    current_draft_version_id: versionId,
    versions: [],
    metadata_revision: 0,
  } as AgentDetail;
}

function draftVersion(): AgentVersion {
  return {
    id: versionId,
    agent_id: agentId,
    version_label: "V1.0",
    state: "draft",
    revision: 0,
    agent_md: "",
    avatar_config: {
      template_id: "wave1-default-head",
      material_theme: "indigo",
      default_expression: "neutral",
      expression_strength: "medium",
      motion_style: "calm",
    },
    voice_fallback_active: true,
    persona_confirmed: false,
    enabled_documents: [],
    publish_blockers: ["agent_md_missing"],
  } as AgentVersion;
}

type MetadataApi = PlatformApi & {
  updateAgentMetadata: (
    agentId: string,
    body: { description: string; expected_metadata_revision?: number },
  ) => Promise<AgentDetail>;
  deleteAgent: (agentId: string, options?: unknown) => Promise<unknown>;
};

const api = {
  agent: vi.fn(async () => draftAgent()),
  versions: vi.fn(async () => [draftVersion()]),
  updateAgentMetadata: vi.fn(
    async (_id: string, body: { description: string }) => ({
      ...draftAgent(body.description),
      metadata_revision: 1,
    }),
  ),
  deleteAgent: vi.fn(async () => undefined),
} as unknown as MetadataApi;

describe("Wave 3 Agent metadata and safe-delete UI", () => {
  beforeEach(() => {
    router.push.mockReset();
    router.replace.mockReset();
    vi.mocked(api.agent).mockClear();
    vi.mocked(api.versions).mockClear();
    vi.mocked(api.updateAgentMetadata).mockClear();
    vi.mocked(api.deleteAgent).mockClear();
    vi.mocked(api.agent).mockResolvedValue(draftAgent());
    vi.mocked(api.versions).mockResolvedValue([draftVersion()]);
    vi.mocked(api.updateAgentMetadata).mockResolvedValue({
      ...draftAgent("A current perspective"),
      metadata_revision: 1,
    } as AgentDetail);
    vi.mocked(api.deleteAgent).mockResolvedValue(undefined);
    mockedUseSession.mockReturnValue({ api } as never);
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("keeps an empty description empty, saves metadata with its CAS revision, and returns by group", async () => {
    render(<AgentOverview agentId={agentId} />);
    await waitFor(() => expect(screen.getByText("Draft Agent")).toBeTruthy());

    expect(screen.queryByText("No description yet")).toBeNull();
    expect(
      screen.queryByText("Define an identity and evidence set."),
    ).toBeNull();
    expect(
      screen
        .getByRole("link", { name: "Return to workspace" })
        .getAttribute("href"),
    ).toBe(`/student/groups/${groupId}`);

    fireEvent.click(screen.getByRole("button", { name: "Edit description" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Description" }), {
      target: { value: "A current perspective" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save description" }));

    await waitFor(() =>
      expect(api.updateAgentMetadata).toHaveBeenCalledWith(agentId, {
        expected_metadata_revision: 0,
        description: "A current perspective",
      }),
    );
    expect(
      await screen.findAllByText("A current perspective"),
    ).not.toHaveLength(0);
  });

  it("requires confirmation before discarding a dirty description or deleting", async () => {
    render(<AgentOverview agentId={agentId} />);
    await waitFor(() => expect(screen.getByText("Draft Agent")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Edit description" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Description" }), {
      target: { value: "Unsaved" },
    });

    vi.mocked(window.confirm).mockReturnValueOnce(false);
    fireEvent.click(screen.getByRole("link", { name: "Return to workspace" }));
    expect(window.confirm).toHaveBeenCalled();
    expect(router.replace).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete Agent" }));
    await waitFor(() =>
      expect(api.deleteAgent).toHaveBeenCalledWith(agentId, expect.anything()),
    );
    expect(router.replace).toHaveBeenCalledWith(`/student/groups/${groupId}`);
  });

  it("refreshes authoritative metadata on a stale CAS while preserving the local draft", async () => {
    const authoritative = draftAgent("Server description");
    authoritative.metadata_revision = 1;
    vi.mocked(api.agent)
      .mockResolvedValueOnce(draftAgent("Original description"))
      .mockResolvedValueOnce(authoritative);
    vi.mocked(api.updateAgentMetadata)
      .mockRejectedValueOnce(
        new PlatformApiError(409, "stale", {
          code: "stale_metadata_revision",
          details: { current_metadata_revision: 1 },
        }),
      )
      .mockResolvedValueOnce({
        ...authoritative,
        description: "Local draft",
        metadata_revision: 2,
      } as AgentDetail);

    render(<AgentOverview agentId={agentId} />);
    await waitFor(() => expect(screen.getByText("Draft Agent")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Edit description" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Description" }), {
      target: { value: "Local draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save description" }));

    await waitFor(() => expect(api.agent).toHaveBeenCalled());
    expect(
      (
        screen.getByRole("textbox", {
          name: "Description",
        }) as HTMLTextAreaElement
      ).value,
    ).toBe("Local draft");
    expect(screen.getByText(/description changed elsewhere/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Save description" }));
    await waitFor(() =>
      expect(api.updateAgentMetadata).toHaveBeenLastCalledWith(agentId, {
        expected_metadata_revision: 1,
        description: "Local draft",
      }),
    );
  });

  it("keeps the row edit control keyboard-focusable and updates GroupWorkspace state", async () => {
    const agent: AgentSummary = {
      id: agentId,
      group_id: groupId,
      name: "Row Agent",
      description: "",
      status: "active",
      current_published_version_id: null,
      current_draft_version_id: versionId,
    } as AgentSummary;
    const updated = {
      ...agent,
      description: "Row description",
      metadata_revision: 1,
    } as AgentSummary;
    const groupApi = {
      ...api,
      group: vi.fn().mockResolvedValue({
        id: groupId,
        course_id: "course-id",
        name: "Bowen group",
        members: [],
      }),
      agents: vi.fn().mockResolvedValue([agent]),
      knowledge: vi.fn().mockResolvedValue([]),
      updateAgentMetadata: vi.fn().mockResolvedValue(updated),
    } as unknown as MetadataApi;
    mockedUseSession.mockReturnValue({ api: groupApi } as never);

    render(<GroupWorkspace groupId={groupId} />);
    await waitFor(() => expect(screen.getByText("Row Agent")).toBeTruthy());
    const edit = screen.getByRole("button", { name: "Edit description" });
    edit.focus();
    expect(document.activeElement).toBe(edit);
    fireEvent.click(edit);
    fireEvent.change(screen.getByRole("textbox", { name: "Description" }), {
      target: { value: "Row description" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save description" }));
    await waitFor(() =>
      expect(groupApi.updateAgentMetadata).toHaveBeenCalledWith(agentId, {
        expected_metadata_revision: 0,
        description: "Row description",
      }),
    );
    expect(await screen.findByText("Row description")).toBeTruthy();
  });

  it("shows the authoritative row value after a stale CAS and preserves the local draft", async () => {
    const agent: AgentSummary = {
      id: agentId,
      group_id: groupId,
      name: "Conflict Agent",
      description: "Original server value",
      status: "active",
      current_published_version_id: null,
      current_draft_version_id: versionId,
    } as AgentSummary;
    const authoritative = {
      ...agent,
      description: "Authoritative server value",
      metadata_revision: 1,
    } as AgentSummary;
    const groupApi = {
      ...api,
      group: vi.fn().mockResolvedValue({
        id: groupId,
        course_id: "course-id",
        name: "Bowen group",
        members: [],
      }),
      agents: vi.fn().mockResolvedValue([agent]),
      knowledge: vi.fn().mockResolvedValue([]),
      agent: vi.fn().mockResolvedValue(authoritative),
      updateAgentMetadata: vi
        .fn()
        .mockRejectedValueOnce({
          status: 409,
          code: "stale_metadata_revision",
        })
        .mockResolvedValueOnce({
          ...authoritative,
          description: "Local row draft",
          metadata_revision: 2,
        }),
    } as unknown as MetadataApi;
    mockedUseSession.mockReturnValue({ api: groupApi } as never);

    render(<GroupWorkspace groupId={groupId} />);
    await waitFor(() =>
      expect(screen.getByText("Conflict Agent")).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit description" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Description" }), {
      target: { value: "Local row draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save description" }));
    await waitFor(() => expect(groupApi.agent).toHaveBeenCalledWith(agentId));
    expect(
      (
        screen.getByRole("textbox", {
          name: "Description",
        }) as HTMLTextAreaElement
      ).value,
    ).toBe("Local row draft");
    expect(
      screen.getByLabelText("Current Agent metadata").textContent,
    ).toContain("Authoritative server value");

    fireEvent.click(screen.getByRole("button", { name: "Save description" }));
    await waitFor(() =>
      expect(groupApi.updateAgentMetadata).toHaveBeenLastCalledWith(agentId, {
        expected_metadata_revision: 1,
        description: "Local row draft",
      }),
    );
  });

  it("renders empty descriptions and metadata labels in Chinese without a fallback", async () => {
    render(
      <LocaleProvider initialLocale="zh">
        <AgentOverview agentId={agentId} />
      </LocaleProvider>,
    );
    await waitFor(() => expect(screen.getByText("Draft Agent")).toBeTruthy());
    expect(screen.queryByText("暂无简介")).toBeNull();
    expect(screen.getByRole("button", { name: "编辑简介" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "编辑简介" }));
    expect(screen.getByRole("button", { name: "保存简介" })).toBeTruthy();
  });

  it("labels teacher description as current metadata while history remains separate", async () => {
    const teacherApi = {
      agent: vi.fn().mockResolvedValue({
        ...draftAgent("Current mutable description"),
        current_published_version_id: "published-version",
      }),
      versions: vi.fn().mockResolvedValue([
        {
          ...draftVersion(),
          id: "published-version",
          state: "published",
          knowledge_snapshot_id: "snapshot-id",
          agent_md: "# Frozen prompt",
        },
      ]),
      snapshot: vi.fn().mockResolvedValue({
        id: "snapshot-id",
        agent_version_id: "published-version",
        content_hash: "hash",
        total_char_count: 10,
        documents: [],
        created_at: "2026-08-28T00:00:00Z",
      }),
      downloadSnapshot: vi.fn(),
      downloadSnapshotDocument: vi.fn(),
    } as unknown as MetadataApi;
    mockedUseSession.mockReturnValue({ api: teacherApi } as never);

    render(<TeacherAgentDetail agentId={agentId} />);
    await waitFor(() =>
      expect(screen.getByText("Current mutable description")).toBeTruthy(),
    );
    expect(
      screen.getByLabelText("Current Agent metadata").textContent,
    ).toContain("Current mutable description");
  });
});
