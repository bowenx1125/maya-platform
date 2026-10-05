import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentWorkbench } from "../components/agent-workspace";
import { LocaleProvider } from "../components/locale";
import {
  TeacherDashboard,
  TeacherPersonalAgentCreate,
} from "../components/teacher-workspace";
import { useSession } from "../components/session-provider";
import type {
  AgentDetail,
  AgentSummary,
  AgentVersion,
  KnowledgeDocument,
} from "../lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/teacher",
}));

vi.mock("../components/session-provider", () => ({
  useSession: vi.fn(),
}));

const mockedUseSession = vi.mocked(useSession);
const courseId = "teacher-course";
const agentId = "personal-agent";
const versionId = "personal-draft";

function personalAgent(overrides: Partial<AgentDetail> = {}): AgentDetail {
  return {
    id: agentId,
    group_id: null,
    course_id: courseId,
    ownership_scope: "personal",
    visibility: "private",
    name: "Teacher Lens",
    description: "",
    metadata_revision: 0,
    status: "active",
    current_published_version_id: null,
    current_draft_version_id: versionId,
    versions: [],
    ...overrides,
  } as AgentDetail;
}

function privateDocument(): KnowledgeDocument {
  return {
    id: "private-source",
    group_id: null,
    course_id: courseId,
    ownership_scope: "personal",
    visibility: "private",
    can_manage_visibility: true,
    authorization_epoch: 0,
    source_filename: "private-notes.md",
    source_owner_role: "student",
    char_count: 31,
    content_hash: "a".repeat(64),
    index_revision: 1,
    index_status: "ready",
    workspace_state: "active",
    created_at: "2026-09-27T00:00:00Z",
  };
}

function draft(document: KnowledgeDocument): AgentVersion {
  return {
    id: versionId,
    agent_id: agentId,
    version_label: "V1.0",
    state: "draft",
    revision: 0,
    agent_md: "# Teacher Lens\n\nPrivate working copy.",
    avatar_config: {
      template_id: "wave1-default-head",
      material_theme: "demo",
      eye_color: null,
      default_expression: "neutral",
      expression_strength: "medium",
      motion_style: "calm",
    },
    voice_profile_id: null,
    effective_voice_profile_id: null,
    voice_fallback_active: true,
    persona_confirmed: false,
    knowledge_snapshot_id: null,
    enabled_documents: [document],
    publish_blockers: [],
  } as AgentVersion;
}

function teacherSession(api: Record<string, unknown>) {
  return {
    api,
    identityGeneration: 2,
    user: {
      id: "teacher-user",
      display_name: "Maya",
      avatar: null,
      courses: [{ course_id: courseId, role: "teacher" }],
    },
  } as never;
}

afterEach(() => {
  cleanup();
  mockedUseSession.mockReset();
  vi.restoreAllMocks();
});

describe("W1 teacher personal workspace", () => {
  it("lists a personal Agent from the teacher's real course workspace", async () => {
    const agent = personalAgent() as AgentSummary;
    const api = {
      courses: vi
        .fn()
        .mockResolvedValue([
          { id: courseId, code: "MAYA-101", name: "Cultural exchange" },
        ]),
      publishedAgents: vi.fn().mockResolvedValue([]),
      debates: vi.fn().mockResolvedValue([]),
      groups: vi.fn().mockResolvedValue([]),
      workspaceAgents: vi.fn().mockResolvedValue([agent]),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <TeacherDashboard />
      </LocaleProvider>,
    );

    const tile = await screen.findByRole("link", { name: "Teacher Lens" });
    expect(tile.getAttribute("href")).toBe(`/teacher/agents/${agentId}`);
    expect(screen.getByText("Private — only me")).toBeTruthy();
    expect(api.workspaceAgents).toHaveBeenCalledWith(courseId);
    expect(
      screen
        .getByRole("link", { name: "Create AI Knowledge" })
        .getAttribute("href"),
    ).toBe("/teacher/agents/new?flow=ai-knowledge");
    expect(screen.getByRole("link", { name: "New" }).getAttribute("href")).toBe(
      "/teacher/agents/new",
    );
  });

  it("creates a course-scoped Agent with Private as the default visibility", async () => {
    const api = {
      createWorkspaceAgent: vi.fn().mockResolvedValue(personalAgent()),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <TeacherPersonalAgentCreate />
      </LocaleProvider>,
    );

    expect(
      screen.getByText(/A Public personal Agent is shareable/),
    ).toBeTruthy();
    expect(
      screen.getByText(/separate invocation grant to use it/),
    ).toBeTruthy();
    expect(
      screen.getByRole("option", {
        name: "Shareable; students need an explicit grant",
      }),
    ).toBeTruthy();
    const name = screen.getByLabelText("Agent name");
    fireEvent.change(name, { target: { value: "Teacher Lens" } });
    fireEvent.submit(name.closest("form")!);

    await waitFor(() =>
      expect(api.createWorkspaceAgent).toHaveBeenCalledWith(
        courseId,
        "Teacher Lens",
        "",
        expect.objectContaining({ idempotency: expect.any(Object) }),
        "private",
      ),
    );
  });

  it("lets the owner share a private source and personal Agent from the workbench", async () => {
    let agent = personalAgent();
    let document = privateDocument();
    const currentDraft = draft(document);
    const api = {
      version: vi.fn().mockImplementation(async () => currentDraft),
      agent: vi.fn().mockImplementation(async () => agent),
      workspaceDocuments: vi.fn().mockImplementation(async () => [document]),
      ragPreview: vi.fn().mockResolvedValue({
        version_id: versionId,
        total_char_count: document.char_count,
        limit: null,
        document_count: 1,
        index_status: "ready",
        combined_markdown: "# Private notes",
      }),
      avatarTemplates: vi.fn().mockResolvedValue([]),
      updateAgentMetadata: vi.fn().mockImplementation(async (_id, body) => {
        agent = personalAgent({
          visibility: body.visibility,
          metadata_revision: agent.metadata_revision + 1,
        });
        return agent;
      }),
      updateKnowledgeVisibility: vi
        .fn()
        .mockImplementation(async (_id, body) => {
          document = {
            ...document,
            visibility: body.visibility,
            authorization_epoch: document.authorization_epoch + 1,
          };
          return document;
        }),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <AgentWorkbench
          key="teacher-scope"
          actorScopeKey="teacher-user:teacher-course:2"
          backHref="/teacher"
          versionId={versionId}
        />
      </LocaleProvider>,
    );

    await screen.findByRole("heading", { name: "Who can use this Agent" });
    fireEvent.click(screen.getByRole("button", { name: "Make Agent public" }));
    await waitFor(() =>
      expect(api.updateAgentMetadata).toHaveBeenCalledWith(
        agentId,
        expect.objectContaining({
          expected_metadata_revision: 0,
          visibility: "public",
        }),
      ),
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Share source: private-notes.md" }),
    );
    await waitFor(() =>
      expect(api.updateKnowledgeVisibility).toHaveBeenCalledWith(
        "private-source",
        { expected_authorization_epoch: 0, visibility: "public" },
      ),
    );
  });
});
