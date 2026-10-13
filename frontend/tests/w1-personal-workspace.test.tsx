import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentWorkbench } from "../components/agent-workspace";
import { LocaleProvider } from "../components/locale";
import { AppShell } from "../components/app-shell";
import {
  TeacherDashboard,
  TeacherPersonalAgentCreate,
  TeacherStudyformWorkspace,
} from "../components/teacher-workspace";
import { useSession } from "../components/session-provider";
import type {
  AgentDetail,
  AgentSummary,
  AgentVersion,
  KnowledgeDocument,
} from "../lib/api";
import { PlatformApiError } from "../lib/api";

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

function teacherSession(
  api: Record<string, unknown>,
  groups: { group_id: string }[] = [],
) {
  return {
    api,
    identityGeneration: 2,
    user: {
      id: "teacher-user",
      display_name: "Maya",
      avatar: null,
      courses: [{ course_id: courseId, role: "teacher" }],
      groups,
    },
  } as never;
}

afterEach(() => {
  cleanup();
  mockedUseSession.mockReset();
  vi.restoreAllMocks();
});

describe("W1 teacher personal workspace", () => {
  it("shows the same public Agents on Studyform as on Mayaform Home", async () => {
    const agent = personalAgent() as AgentSummary;
    const published = {
      group_name: "",
      author: {
        user_id: "teacher-user",
        display_name: "Maya",
        avatar: null,
      },
      agent: {
        ...agent,
        visibility: "public",
        current_published_version_id: "version-1",
        current_draft_version_id: null,
      },
      current_version: {
        id: "version-1",
        version_label: "V1.0",
        state: "published",
      },
    };
    const api = {
      publishedAgents: vi.fn().mockResolvedValue([published]),
      chatAgents: vi.fn().mockResolvedValue([]),
      groups: vi.fn().mockResolvedValue([]),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherStudyformWorkspace />
        </AppShell>
      </LocaleProvider>,
    );

    const tile = await screen.findByRole("link", { name: "Teacher Lens" });
    expect(tile.getAttribute("href")).toBe(`/teacher/agents/${agentId}`);
    expect(screen.getByText("V1.0")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete" })).toBeTruthy();
    expect(api.publishedAgents).toHaveBeenCalledWith(courseId);
    expect(
      screen.getByRole("link", { name: "Studyform" }).getAttribute("href"),
    ).toBe("/teacher/studyform");
  });

  it("shows the owner's private Agent on Studyform", async () => {
    const api = {
      publishedAgents: vi.fn().mockResolvedValue([]),
      workspaceAgents: vi.fn().mockResolvedValue([personalAgent()]),
      chatAgents: vi.fn().mockResolvedValue([]),
      groups: vi.fn().mockResolvedValue([]),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherStudyformWorkspace />
        </AppShell>
      </LocaleProvider>,
    );

    const tile = await screen.findByRole("link", { name: "Teacher Lens" });
    expect(tile.getAttribute("href")).toBe(`/teacher/agents/${agentId}`);
    expect(screen.queryByText("Draft")).toBeNull();
    expect(api.workspaceAgents).toHaveBeenCalledWith(courseId);
  });

  it("preserves the colleague Home without loading personal Agent lists", async () => {
    const api = {
      courses: vi
        .fn()
        .mockResolvedValue([
          { id: courseId, code: "MAYA-101", name: "Cultural exchange" },
        ]),
      publishedAgents: vi.fn().mockResolvedValue([]),
      debates: vi.fn().mockResolvedValue([]),
      groups: vi.fn().mockResolvedValue([]),
      workspaceAgents: vi.fn().mockResolvedValue([]),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <TeacherDashboard />
      </LocaleProvider>,
    );

    await screen.findByRole("heading", { name: /Welcome/ });
    expect(api.workspaceAgents).not.toHaveBeenCalled();
    expect(screen.queryByText("Personal Agents · 0")).toBeNull();
    expect(screen.getByRole("heading", { name: "Guide" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Publish an Agent/ })).toBeTruthy();
  });

  it("creates a course-scoped Agent with Private as the default visibility", async () => {
    const api = {
      createWorkspaceAgent: vi.fn().mockResolvedValue(personalAgent()),
      workspaceDocuments: vi.fn().mockResolvedValue([]),
      knowledgeSets: vi.fn().mockResolvedValue([]),
      avatarTemplates: vi.fn().mockResolvedValue([]),
      updateDraft: vi.fn(async () =>
        draft({ ...privateDocument(), id: "unused" }),
      ),
      publish: vi.fn(async () => ({
        ...draft(privateDocument()),
        state: "published",
        publish_blockers: [],
      })),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherPersonalAgentCreate />
        </AppShell>
      </LocaleProvider>,
    );

    expect(
      (await screen.findByRole("button", { name: "Private" })).getAttribute(
        "aria-pressed",
      ),
    ).toBe("true");
    expect(
      screen
        .getByRole("button", { name: "Public" })
        .getAttribute("aria-pressed"),
    ).toBe("false");
    expect(screen.queryByRole("option", { name: "Private" })).toBeNull();
    expect(screen.queryByLabelText("Note")).toBeNull();
    expect(
      screen.queryByText(/A Public personal Agent is shareable/),
    ).toBeNull();
    expect(api.createWorkspaceAgent).not.toHaveBeenCalled();
    const name = screen.getByLabelText("Name");
    fireEvent.change(name, { target: { value: "Teacher Lens" } });
    fireEvent.change(screen.getByRole("textbox", { name: "AGENT.md editor" }), {
      target: { value: "# Teacher Lens" },
    });
    const done = screen.getByRole("button", { name: "Done" });
    await waitFor(() => expect(done).not.toHaveProperty("disabled", true));
    fireEvent.click(done);

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

  // Bug (2026-10-13): a new Agent's Brainform listed another Agent's private
  // file and the Knowledge of a deleted Agent, which Brainform itself hides.
  it("offers a new Agent only the library Brainform lists", async () => {
    const knowledgeSet = (id: string, name: string) => ({
      id,
      display_name: name,
      can_edit: true,
    });
    const api = {
      createWorkspaceAgent: vi.fn().mockResolvedValue(personalAgent()),
      workspaceDocuments: vi.fn().mockResolvedValue([
        privateDocument(),
        {
          ...privateDocument(),
          id: "shared-source",
          visibility: "public",
          source_filename: "shared-notes.md",
        },
      ]),
      knowledgeSets: vi
        .fn()
        .mockResolvedValue([
          knowledgeSet("live-set", "Live Knowledge"),
          knowledgeSet("orphan-set", "Deleted Agent Knowledge"),
        ]),
      brainformKnowledge: vi
        .fn()
        .mockResolvedValue([{ canonical_set_id: "live-set" }]),
      avatarTemplates: vi.fn().mockResolvedValue([]),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherPersonalAgentCreate />
        </AppShell>
      </LocaleProvider>,
    );

    expect(
      await screen.findByRole("checkbox", { name: "shared-notes.md" }),
    ).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Live Knowledge" })).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: "private-notes.md" })).toBeNull();
    expect(
      screen.queryByRole("checkbox", { name: "Deleted Agent Knowledge" }),
    ).toBeNull();
  });

  // Owner decision (2026-10-12): a teacher creates personal voices that only
  // that teacher may choose; Studyform lists those, never a group's.
  it("lists and creates a teacher's own personal voices", async () => {
    const api = {
      workspaceAgents: vi.fn().mockResolvedValue([]),
      chatAgents: vi.fn().mockResolvedValue([]),
      groups: vi.fn().mockResolvedValue([]),
      voiceProfiles: vi.fn().mockResolvedValue([]),
      personalVoiceProfiles: vi.fn().mockResolvedValue([
        {
          id: "teacher-voice",
          scope: "personal",
          group_id: null,
          status: "ready",
          source_filename: "teacher-voice.wav",
          created_at: "2026-10-07T00:00:00Z",
          can_manage: true,
        },
      ]),
      enrollVoice: vi.fn(),
      enrollPersonalVoice: vi.fn(),
      createVoicePreview: vi.fn(),
    };
    mockedUseSession.mockReturnValue(
      teacherSession(api, [{ group_id: "teacher-group" }]),
    );
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherStudyformWorkspace />
        </AppShell>
      </LocaleProvider>,
    );

    const heading = await screen.findByRole("heading", { name: "Voices" });
    const voices = heading.closest("section") as HTMLElement;
    expect(await within(voices).findByText("teacher-voice.wav")).toBeTruthy();
    expect(
      within(voices).getByRole("button", { name: "Preview" }),
    ).toBeTruthy();
    expect(api.personalVoiceProfiles).toHaveBeenCalledWith(courseId);
    expect(api.voiceProfiles).not.toHaveBeenCalled();
    expect(api.groups).not.toHaveBeenCalled();
    expect(api.enrollVoice).not.toHaveBeenCalled();
  });

  it("shows an error when the personal voice list fails", async () => {
    const api = {
      workspaceAgents: vi.fn().mockResolvedValue([]),
      chatAgents: vi.fn().mockResolvedValue([]),
      groups: vi.fn().mockResolvedValue([]),
      voiceProfiles: vi.fn().mockResolvedValue([]),
      personalVoiceProfiles: vi
        .fn()
        .mockRejectedValue(new PlatformApiError(500, "temporary_failure")),
      enrollVoice: vi.fn(),
      enrollPersonalVoice: vi.fn(),
      createVoicePreview: vi.fn(),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherStudyformWorkspace />
        </AppShell>
      </LocaleProvider>,
    );

    const heading = await screen.findByRole("heading", { name: "Voices" });
    const voices = heading.closest("section") as HTMLElement;
    await waitFor(() =>
      expect(api.personalVoiceProfiles).toHaveBeenCalledWith(courseId),
    );
    expect(await within(voices).findByRole("alert")).toBeTruthy();
    expect(api.voiceProfiles).not.toHaveBeenCalled();
  });

  // RAG rows carry only the checkbox and file name, like the Knowledge list.
  it("keeps the workbench RAG list to the checkbox and file name", async () => {
    let agent = personalAgent();
    let document = privateDocument();
    const currentDraft = draft(document);
    const api = {
      version: vi.fn().mockImplementation(async () => currentDraft),
      agent: vi.fn().mockImplementation(async () => agent),
      workspaceDocuments: vi.fn().mockImplementation(async () => [document]),
      knowledgeSets: vi.fn().mockResolvedValue([]),
      agentKnowledgeSets: vi.fn().mockImplementation(async () => ({
        agent_id: agent.id,
        agent_metadata_revision: agent.metadata_revision,
        sets: [],
      })),
      replaceAgentKnowledgeSets: vi.fn(async (_id, body) => ({
        agent_id: agent.id,
        agent_metadata_revision: body.expected_agent_metadata_revision + 1,
        sets: [],
      })),
      voiceProfiles: vi.fn().mockResolvedValue([]),
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

    expect(
      await screen.findByRole("checkbox", { name: "private-notes.md" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Share source/ })).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Make source private/ }),
    ).toBeNull();
    expect(screen.queryByText("Ready")).toBeNull();
    expect(screen.queryByRole("group", { name: "Visibility" })).toBeNull();
    expect(
      screen.queryByText("Shareable; students need an explicit grant"),
    ).toBeNull();
    expect(api.updateAgentMetadata).not.toHaveBeenCalled();
    expect(api.updateKnowledgeVisibility).not.toHaveBeenCalled();
  });
});
