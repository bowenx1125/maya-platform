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
    course_id: "course-id",
    ownership_scope: "group",
    visibility: "public",
    name: "First Agent",
    description: "",
    metadata_revision: 0,
    can_edit: true,
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
    course_id: "course-id",
    ownership_scope: "group",
    visibility: "public",
    can_manage_visibility: false,
    authorization_epoch: 0,
    source_filename: "notes.md",
    source_owner_role: "student",
    content_hash: "a".repeat(64),
    created_at: "2026-10-04T00:00:00Z",
    index_revision: 0,
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
    useSessionMock.mockReturnValue({
      api: {
        createAgent,
        group: vi.fn().mockResolvedValue({
          id: "group-id",
          course_id: "course-id",
          name: "Group",
        }),
        knowledge: vi.fn().mockResolvedValue([]),
        knowledgeSets: vi.fn().mockResolvedValue([]),
        avatarTemplates: vi.fn().mockResolvedValue([]),
        voiceProfiles: vi.fn().mockResolvedValue([]),
        updateDraft: vi.fn(async () => draftVersion()),
        publish: vi.fn(async () => draftVersion("published")),
      },
      user: { groups: [] },
    });

    render(
      <AppShell role="student">
        <CreateAgentForm groupId="group-id" />
      </AppShell>,
    );
    const name = await screen.findByLabelText("Name");
    fireEvent.change(name, { target: { value: "First Agent" } });
    fireEvent.change(
      await screen.findByRole("textbox", { name: "AGENT.md editor" }),
      { target: { value: "# First Agent" } },
    );
    const done = screen.getByRole("button", { name: "Done" });
    await waitFor(() => expect(done).not.toHaveProperty("disabled", true));
    fireEvent.click(done);

    await waitFor(() => expect(createAgent).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("alert").textContent).toContain(
      "Maya could not be reached. Check your connection and try again.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(createAgent).toHaveBeenCalledTimes(2));
    expect(keys[1]).toBe(keys[0]);

    fireEvent.change(name, { target: { value: "Second Agent" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(createAgent).toHaveBeenCalledTimes(3));
    expect(keys[2]).not.toBe(keys[1]);
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/student/groups/group-id"),
    );
  });

  it("reuses a publish key when the first request is ambiguous", async () => {
    const keys: string[] = [];
    const version = draftVersion();
    const published = draftVersion("published");
    const api = {
      version: vi.fn().mockResolvedValue(version),
      agent: vi.fn().mockResolvedValue(createdAgent()),
      knowledge: vi.fn().mockResolvedValue([]),
      knowledgeSets: vi.fn().mockResolvedValue([]),
      agentKnowledgeSets: vi.fn().mockResolvedValue({
        agent_id: "agent-id",
        agent_metadata_revision: 0,
        sets: [],
      }),
      replaceAgentKnowledgeSets: vi.fn(async (_id, body) => ({
        agent_id: "agent-id",
        agent_metadata_revision: body.expected_agent_metadata_revision + 1,
        sets: [],
      })),
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
        "Maya could not be reached. Check your connection and try again.",
      );
    });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(api.publish).toHaveBeenCalledTimes(2));
    expect(keys[1]).toBe(keys[0]);
  });

  it("shows provider errors without an extra teacher-approval link", async () => {
    const api = {
      version: vi.fn().mockResolvedValue(draftVersion()),
      agent: vi.fn().mockResolvedValue(createdAgent()),
      knowledge: vi.fn().mockResolvedValue([]),
      knowledgeSets: vi.fn().mockResolvedValue([]),
      agentKnowledgeSets: vi.fn().mockResolvedValue({
        agent_id: "agent-id",
        agent_metadata_revision: 0,
        sets: [],
      }),
      replaceAgentKnowledgeSets: vi.fn(async (_id, body) => ({
        agent_id: "agent-id",
        agent_metadata_revision: body.expected_agent_metadata_revision + 1,
        sets: [],
      })),
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

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Teacher confirmation required.",
    );
    expect(api.publish).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link", { name: "Review" })).toBeNull();
    expect(
      screen.queryByRole("link", {
        name: /provider approvals/i,
      }),
    ).toBeNull();
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
        "Maya could not be reached. Check your connection and try again.",
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
      version: vi.fn().mockResolvedValue(version),
      agent: vi.fn().mockResolvedValue(agent),
      versions: vi.fn().mockResolvedValue([version]),
      knowledge: vi.fn().mockResolvedValue([]),
      knowledgeSets: vi.fn().mockResolvedValue([]),
      agentKnowledgeSets: vi.fn().mockResolvedValue({
        agent_id: agent.id,
        agent_metadata_revision: agent.metadata_revision,
        sets: [],
      }),
      avatarTemplates: vi.fn().mockResolvedValue([]),
      voiceProfiles: vi.fn().mockResolvedValue([]),
      ragPreview: vi.fn().mockResolvedValue({
        document_count: 0,
        total_char_count: 0,
        index_status: "ready",
        combined_markdown: "",
      }),
      updateDraft: vi.fn(async () => draftVersion()),
      publish: vi.fn(async () => draftVersion("published")),
      nextVersion,
    };
    useSessionMock.mockReturnValue({ api, user: { groups: [] } });

    render(
      <AppShell role="student">
        <AgentWorkbench versionId="version-id" publishOnDone />
      </AppShell>,
    );
    const editor = await screen.findByRole("textbox", {
      name: "AGENT.md editor",
    });
    expect(nextVersion).not.toHaveBeenCalled();
    fireEvent.change(editor, { target: { value: "# Updated agent" } });
    const done = screen.getByRole("button", { name: "Done" });
    await waitFor(() => expect(done).not.toHaveProperty("disabled", true));
    fireEvent.click(done);
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "Maya could not be reached. Check your connection and try again.",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(nextVersion).toHaveBeenCalledTimes(2));
    expect(keys[1]).toBe(keys[0]);
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
      knowledgeSets: vi.fn().mockResolvedValue([]),
      agentKnowledgeSets: vi.fn().mockResolvedValue({
        agent_id: agent.id,
        agent_metadata_revision: agent.metadata_revision,
        sets: [],
      }),
      replaceAgentKnowledgeSets: vi.fn(async (_id, body) => ({
        agent_id: agent.id,
        agent_metadata_revision: body.expected_agent_metadata_revision + 1,
        sets: [],
      })),
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
    // RAG is uploaded inside its Agent; an uncertain upload retries with
    // the same key rather than adding the file twice.
    const input = await screen.findByLabelText("Upload RAG");
    expect(screen.queryByRole("link", { name: "New" })).toBeNull();
    const file = new File(["# Notes\n\nA source."], "notes.md", {
      type: "text/markdown",
    });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(uploadKnowledge).toHaveBeenCalledTimes(1));
    expect(uploadKnowledge.mock.calls[0][0]).toBe("group-id");
    expect(uploadKnowledge.mock.calls[0][1]).toBe("version-id");
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(uploadKnowledge).toHaveBeenCalledTimes(2));
    expect(keys[1]).toBe(keys[0]);
  });

  it("offers Retry for a retryable OCR import failure with a fresh key", async () => {
    const keys: string[] = [];
    const version = draftVersion();
    const agent = createdAgent();
    const document = failedDocument();
    const uploadKnowledge = vi.fn(async (...args: unknown[]) => {
      const options = args[4] as { idempotency?: { key: string } } | undefined;
      keys.push(options?.idempotency?.key ?? "missing");
      if (keys.length === 1) {
        throw new PlatformApiError(
          422,
          "Local OCR timed out on this scanned PDF.",
          {
            code: "knowledge_import_ocr_timeout",
            details: { reason: "ocr_timeout", retryable: true },
          },
        );
      }
      return { agent_version: version, document };
    });
    const api = {
      version: vi.fn().mockResolvedValue(version),
      agent: vi.fn().mockResolvedValue(agent),
      knowledge: vi.fn().mockResolvedValue([]),
      knowledgeSets: vi.fn().mockResolvedValue([]),
      agentKnowledgeSets: vi.fn().mockResolvedValue({
        agent_id: agent.id,
        agent_metadata_revision: agent.metadata_revision,
        sets: [],
      }),
      replaceAgentKnowledgeSets: vi.fn(async (_id, body) => ({
        agent_id: agent.id,
        agent_metadata_revision: body.expected_agent_metadata_revision + 1,
        sets: [],
      })),
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
    const input = await screen.findByLabelText("Upload RAG");
    const file = new File(["%PDF-1.7 scan"], "scan.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(input, { target: { files: [file] } });
    const alert = await screen.findByRole("alert");
    await waitFor(() =>
      expect(alert.textContent).toContain("Local OCR timed out"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(uploadKnowledge).toHaveBeenCalledTimes(2));
    expect(uploadKnowledge.mock.calls[1][2]).toBe(file);
    // A 422 never reached the server, so the retry rotates to a fresh key.
    expect(keys[1]).not.toBe(keys[0]);
  });

  it("does not offer Retry when the import failure is not retryable", async () => {
    const version = draftVersion();
    const agent = createdAgent();
    const uploadKnowledge = vi.fn(async () => {
      throw new PlatformApiError(
        422,
        "The document could not be read as a valid PDF/Word file.",
        {
          code: "knowledge_import_invalid",
          details: { reason: "invalid_pdf", retryable: false },
        },
      );
    });
    const api = {
      version: vi.fn().mockResolvedValue(version),
      agent: vi.fn().mockResolvedValue(agent),
      knowledge: vi.fn().mockResolvedValue([]),
      knowledgeSets: vi.fn().mockResolvedValue([]),
      agentKnowledgeSets: vi.fn().mockResolvedValue({
        agent_id: agent.id,
        agent_metadata_revision: agent.metadata_revision,
        sets: [],
      }),
      replaceAgentKnowledgeSets: vi.fn(async (_id, body) => ({
        agent_id: agent.id,
        agent_metadata_revision: body.expected_agent_metadata_revision + 1,
        sets: [],
      })),
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
    const input = await screen.findByLabelText("Upload RAG");
    const file = new File(["broken"], "corrupt.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(input, { target: { files: [file] } });
    const alert = await screen.findByRole("alert");
    await waitFor(() =>
      expect(alert.textContent).toContain("Use a readable PDF, Word (.docx)"),
    );
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(uploadKnowledge).toHaveBeenCalledTimes(1);
  });
});
