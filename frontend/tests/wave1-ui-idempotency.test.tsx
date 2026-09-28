import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PlatformApiError,
  type AgentDetail,
  type AgentVersion,
  type KnowledgeDocument,
} from "../lib/api";

const useSessionMock = vi.hoisted(() => vi.fn());
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/student/agents/agent-id",
}));
vi.mock("../components/session-provider", () => ({
  useSession: useSessionMock,
}));

import { AgentOverview, AgentWorkbench } from "../components/agent-workspace";
import { AppShell } from "../components/app-shell";
import { KnowledgeLibrary } from "../components/knowledge";
import { CreateAgentForm } from "../components/student-workspace";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useSessionMock.mockReset();
  router.push.mockReset();
  router.replace.mockReset();
});

function createdAgent(): AgentDetail {
  return {
    id: "agent-id",
    group_id: "group-id",
    name: "First Agent",
    description: "",
    metadata_revision: 0,
    status: "active",
    current_draft_version_id: "version-id",
    current_published_version_id: null,
    versions: [],
  } as AgentDetail;
}

function failedDocument(): KnowledgeDocument {
  return {
    id: "document-id",
    group_id: "group-id",
    source_filename: "notes.md",
    source_owner_role: "student",
    char_count: 128,
    workspace_state: "active",
    index_status: "failed",
  } as KnowledgeDocument;
}

function archivedAgent(): AgentDetail {
  return {
    ...createdAgent(),
    status: "archived",
    current_draft_version_id: null,
  } as AgentDetail;
}

function draftVersion(state: AgentVersion["state"] = "draft"): AgentVersion {
  return {
    id: "version-id",
    agent_id: "agent-id",
    version_label: "V1.0",
    state,
    revision: 0,
    agent_md: "# Agent",
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
    publish_blockers: [],
  } as AgentVersion;
}

describe("Wave 1A UI idempotency wiring", () => {
  it("reuses create key on an ambiguous retry and rotates after changed input", async () => {
    const keys: string[] = [];
    const createAgent = vi.fn(async (...args: unknown[]) => {
      const options = args[3] as { idempotency?: { key: string } } | undefined;
      keys.push(options?.idempotency?.key ?? "missing");
      if (keys.length < 3) throw new TypeError("connection reset");
      return createdAgent();
    });
    useSessionMock.mockReturnValue({ api: { createAgent } });

    render(
      <AppShell role="student">
        <CreateAgentForm groupId="group-id" />
      </AppShell>,
    );
    const name = screen.getByLabelText("Agent name");
    fireEvent.change(name, { target: { value: "First Agent" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(createAgent).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("alert").textContent).toContain("Request failed");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(createAgent).toHaveBeenCalledTimes(2));
    expect(keys[1]).toBe(keys[0]);

    fireEvent.change(name, { target: { value: "Second Agent" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(createAgent).toHaveBeenCalledTimes(3));
    expect(keys[2]).not.toBe(keys[1]);
    expect(router.push).toHaveBeenCalledWith(
      "/student/agent-versions/version-id/edit",
    );
  });

  it("reuses a document reindex key when the first request is ambiguous", async () => {
    const keys: string[] = [];
    const document = failedDocument();
    const knowledge = vi.fn().mockResolvedValue([document]);
    const reindex = vi.fn(async (...args: unknown[]) => {
      const options = args[1] as { idempotency?: { key: string } } | undefined;
      keys.push(options?.idempotency?.key ?? "missing");
      if (keys.length === 1) throw new TypeError("request timed out");
      return {};
    });
    useSessionMock.mockReturnValue({ api: { knowledge, reindex } });

    render(<KnowledgeLibrary groupId="group-id" />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Reindex" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Reindex" }));

    await waitFor(() => expect(reindex).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(reindex).toHaveBeenCalledTimes(2));
    expect(keys[1]).toBe(keys[0]);
  });

  it("reuses a publish key when the first request is ambiguous", async () => {
    const keys: string[] = [];
    const version = draftVersion();
    const published = draftVersion("published");
    const api = {
      version: vi.fn().mockResolvedValue(version),
      agent: vi.fn().mockResolvedValue(createdAgent()),
      knowledge: vi.fn().mockResolvedValue([]),
      avatarTemplates: vi.fn().mockResolvedValue([]),
      voiceProfiles: vi.fn().mockResolvedValue([]),
      ragPreview: vi.fn().mockResolvedValue({
        document_count: 0,
        total_char_count: 0,
        index_status: "ready",
        combined_markdown: "",
      }),
      publish: vi.fn(async (...args: unknown[]) => {
        const options = args[2] as
          { idempotency?: { key: string } } | undefined;
        keys.push(options?.idempotency?.key ?? "missing");
        if (keys.length === 1) throw new TypeError("connection reset");
        return published;
      }),
    };
    useSessionMock.mockReturnValue({ api });

    render(
      <AppShell role="student">
        <AgentWorkbench versionId="version-id" />
      </AppShell>,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Done" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(api.publish).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("alert").textContent).toContain(
        "connection reset",
      );
    });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(api.publish).toHaveBeenCalledTimes(2));
    expect(keys[1]).toBe(keys[0]);
  });

  it("links to teacher-only version approvals without consuming a manifest hash", async () => {
    const api = {
      version: vi.fn().mockResolvedValue(draftVersion()),
      agent: vi.fn().mockResolvedValue(createdAgent()),
      knowledge: vi.fn().mockResolvedValue([]),
      avatarTemplates: vi.fn().mockResolvedValue([]),
      voiceProfiles: vi.fn().mockResolvedValue([]),
      ragPreview: vi.fn().mockResolvedValue({
        document_count: 0,
        total_char_count: 0,
        index_status: "ready",
        combined_markdown: "",
      }),
      publish: vi.fn().mockRejectedValue(
        new PlatformApiError(409, "Teacher confirmation required.", {
          code: "provider_confirmation_required",
          message: "Teacher confirmation required.",
        }),
      ),
    };
    useSessionMock.mockReturnValue({ api });

    render(
      <AppShell role="student">
        <AgentWorkbench versionId="version-id" />
      </AppShell>,
    );
    await screen.findByRole("button", { name: "Done" });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    const link = await screen.findByRole("link", {
      name: "Review",
    });
    expect(link.getAttribute("href")).toBe(
      "/teacher/provider-approvals/agent-versions/version-id",
    );
    expect(link.textContent).not.toMatch(
      /manifest|qwen|workspace|https?:\/\//i,
    );
  });

  it("replays safe delete through the action-specific retry path", async () => {
    const keys: string[] = [];
    const agent = createdAgent();
    const deleteAgent = vi.fn(async (...args: unknown[]) => {
      const options = args[1] as { idempotency?: { key: string } } | undefined;
      keys.push(options?.idempotency?.key ?? "missing");
      if (keys.length === 1) throw new TypeError("connection reset");
      return undefined;
    });
    const api = {
      agent: vi.fn().mockResolvedValue(agent),
      versions: vi.fn().mockResolvedValue([]),
      deleteAgent,
    };
    useSessionMock.mockReturnValue({ api });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <AppShell role="student">
        <AgentOverview agentId="agent-id" />
      </AppShell>,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Delete" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "connection reset",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(deleteAgent).toHaveBeenCalledTimes(2));
    expect(keys[1]).toBe(keys[0]);
    expect(window.confirm).toHaveBeenCalledTimes(1);
  });

  it("keeps legacy archived Agents discoverable for delete without archive actions", async () => {
    const agent = archivedAgent();
    const api = {
      agent: vi.fn().mockResolvedValue(agent),
      versions: vi.fn().mockResolvedValue([]),
      deleteAgent: vi.fn().mockResolvedValue(undefined),
    };
    useSessionMock.mockReturnValue({ api });

    render(<AgentOverview agentId="agent-id" />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Delete" })).toBeTruthy(),
    );
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Unarchive" })).toBeNull();
  });

  it("replays next-version creation through its action-specific retry", async () => {
    const keys: string[] = [];
    const version = draftVersion("published");
    const agent = {
      ...createdAgent(),
      current_draft_version_id: null,
      current_published_version_id: version.id,
    } as AgentDetail;
    const nextVersion = vi.fn(async (...args: unknown[]) => {
      const options = args[1] as { idempotency?: { key: string } } | undefined;
      keys.push(options?.idempotency?.key ?? "missing");
      if (keys.length === 1) throw new TypeError("connection reset");
      return draftVersion();
    });
    const api = {
      agent: vi.fn().mockResolvedValue(agent),
      versions: vi.fn().mockResolvedValue([version]),
      nextVersion,
    };
    useSessionMock.mockReturnValue({ api });

    render(
      <AppShell role="student">
        <AgentOverview agentId="agent-id" />
      </AppShell>,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "connection reset",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(nextVersion).toHaveBeenCalledTimes(2));
    expect(keys[1]).toBe(keys[0]);
    expect(router.push).toHaveBeenCalledWith(
      "/student/agent-versions/version-id/edit",
    );
  });

  it("replays knowledge upload through the action-specific retry path", async () => {
    const keys: string[] = [];
    const version = draftVersion();
    const agent = createdAgent();
    const document = failedDocument();
    const uploadKnowledge = vi.fn(async (...args: unknown[]) => {
      const options = args[4] as { idempotency?: { key: string } } | undefined;
      keys.push(options?.idempotency?.key ?? "missing");
      if (keys.length === 1) throw new TypeError("connection reset");
      return { agent_version: version, document };
    });
    const api = {
      version: vi.fn().mockResolvedValue(version),
      agent: vi.fn().mockResolvedValue(agent),
      knowledge: vi.fn().mockResolvedValue([]),
      avatarTemplates: vi.fn().mockResolvedValue([]),
      voiceProfiles: vi.fn().mockResolvedValue([]),
      ragPreview: vi.fn().mockResolvedValue({
        document_count: 0,
        total_char_count: 0,
        index_status: "ready",
        combined_markdown: "",
      }),
      uploadKnowledge,
    };
    useSessionMock.mockReturnValue({ api });

    render(
      <AppShell role="student">
        <AgentWorkbench versionId="version-id" />
      </AppShell>,
    );
    await waitFor(() =>
      expect(screen.getAllByLabelText("Upload")).toHaveLength(2),
    );
    const fileInput = screen.getAllByLabelText("Upload")[1];
    fireEvent.change(fileInput, {
      target: { files: [new File(["# one"], "one.md")] },
    });
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "connection reset",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(uploadKnowledge).toHaveBeenCalledTimes(2));
    expect(keys[1]).toBe(keys[0]);
  });

  it("replays hide without asking for confirmation a second time", async () => {
    const keys: string[] = [];
    const document = failedDocument();
    const hidden = { ...document, workspace_state: "hidden" };
    const knowledge = vi.fn().mockResolvedValue([document]);
    const hideKnowledge = vi.fn(async (...args: unknown[]) => {
      const options = args[1] as { idempotency?: { key: string } } | undefined;
      keys.push(options?.idempotency?.key ?? "missing");
      if (keys.length === 1) throw new TypeError("connection reset");
      return hidden;
    });
    const api = { knowledge, hideKnowledge };
    useSessionMock.mockReturnValue({ api });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<KnowledgeLibrary groupId="group-id" />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Delete" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "connection reset",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(hideKnowledge).toHaveBeenCalledTimes(2));
    expect(keys[1]).toBe(keys[0]);
    expect(window.confirm).toHaveBeenCalledTimes(1);
  });

  it("does not replay reindex after a successful mutation's refresh fails", async () => {
    const document = failedDocument();
    const knowledge = vi
      .fn()
      .mockResolvedValueOnce([document])
      .mockRejectedValueOnce(new TypeError("refresh unavailable"))
      .mockResolvedValueOnce([document]);
    const reindex = vi.fn().mockResolvedValue({});
    const api = { knowledge, reindex };
    useSessionMock.mockReturnValue({ api });

    render(<KnowledgeLibrary groupId="group-id" />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Reindex" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Reindex" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "refresh unavailable",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(knowledge).toHaveBeenCalledTimes(3));
    expect(reindex).toHaveBeenCalledTimes(1);
  });
});
