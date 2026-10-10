import {
  act,
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
  it("keeps personal Agent lists in Studyform, not on Mayaform Home", async () => {
    const agent = personalAgent() as AgentSummary;
    const api = {
      workspaceAgents: vi.fn().mockResolvedValue([agent]),
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
    const visibility = screen.getByText("Private", { exact: true });
    expect(visibility.getAttribute("data-ui-guide")).toBe("agent.visibility");
    expect(visibility.getAttribute("tabindex")).toBe("0");
    expect(screen.queryByText("Private — only me")).toBeNull();
    expect(
      screen.queryByText("Shareable; students need an explicit grant"),
    ).toBeNull();
    expect(api.workspaceAgents).toHaveBeenCalledWith(courseId);
    expect(
      screen.getByRole("link", { name: "Studyform" }).getAttribute("href"),
    ).toBe("/teacher/studyform");
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
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <TeacherPersonalAgentCreate />
      </LocaleProvider>,
    );

    expect(
      screen.getByRole("option", {
        name: "Private",
      }),
    ).toBeTruthy();
    expect(screen.getByRole("option", { name: "Public" })).toBeTruthy();
    expect(
      screen.queryByText(/A Public personal Agent is shareable/),
    ).toBeNull();
    const name = screen.getByLabelText("Name");
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

  it("loads the shared VoiceLibrary only for a teacher's explicit group scope", async () => {
    const groupId = "teacher-group";
    const api = {
      workspaceAgents: vi.fn().mockResolvedValue([]),
      chatAgents: vi.fn().mockResolvedValue([]),
      groups: vi
        .fn()
        .mockResolvedValue([
          { id: groupId, course_id: courseId, name: "Cultural exchange" },
        ]),
      voiceProfiles: vi.fn().mockResolvedValue([
        {
          id: "teacher-voice",
          scope: "group",
          group_id: groupId,
          status: "ready",
          source_filename: "teacher-voice.wav",
          created_at: "2026-10-07T00:00:00Z",
        },
      ]),
      enrollVoice: vi.fn(),
      createVoicePreview: vi.fn(),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherStudyformWorkspace initialGroupId={groupId} />
        </AppShell>
      </LocaleProvider>,
    );

    const heading = await screen.findByRole("heading", {
      name: "Voices",
    });
    const voices = heading.closest("section") as HTMLElement;
    expect(
      within(voices).queryByRole("combobox", { name: "Group" }),
    ).toBeNull();
    expect(
      await within(voices).findByRole("button", { name: "teacher-voice.wav" }),
    ).toBeTruthy();
    expect(
      within(voices).getByRole("button", { name: "Preview" }),
    ).toBeTruthy();
    expect(within(voices).getByText("Cultural exchange")).toBeTruthy();
    expect(api.voiceProfiles).toHaveBeenCalledWith(groupId);

    const agents = screen
      .getByRole("heading", { name: /^Agents/ })
      .closest("section") as HTMLElement;
    const agentNew = within(agents).getByRole("link", { name: "New" });
    expect(agentNew.getAttribute("href")).toBe("/teacher/agents/new");
    expect(agentNew.textContent?.trim()).toBe("");
    expect(
      within(screen.getByRole("navigation")).queryByRole("link", {
        name: "New",
      }),
    ).toBeNull();
    const voiceNew = within(voices).getByRole("button", { name: "New" });
    fireEvent.click(voiceNew);
    await screen.findByLabelText(
      "Please upload a 10–15-second audio clip of yourself reading a short passage (16-bit WAV, MP3 or M4A; max 10 MB).",
    );
    const sidebar = within(screen.getByRole("navigation"));
    expect(sidebar.getByRole("button", { name: "Back" })).toBeTruthy();
    expect(
      (sidebar.getByRole("button", { name: "Done" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      within(screen.getByRole("main")).queryByRole("button", { name: "Back" }),
    ).toBeNull();
    expect(
      within(screen.getByRole("main")).queryByRole("button", { name: "Done" }),
    ).toBeNull();
    expect(api.enrollVoice).not.toHaveBeenCalled();
    expect(api.createVoicePreview).not.toHaveBeenCalled();
  });

  it("opens Teacher Voice New for the course groups without a group picker", async () => {
    const groupId = "teacher-group";
    const api = {
      workspaceAgents: vi.fn().mockResolvedValue([]),
      chatAgents: vi.fn().mockResolvedValue([]),
      groups: vi
        .fn()
        .mockResolvedValue([
          { id: groupId, course_id: courseId, name: "Cultural exchange" },
        ]),
      voiceProfiles: vi.fn().mockResolvedValue([]),
      enrollVoice: vi.fn(),
      createVoicePreview: vi.fn(),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherStudyformWorkspace initialMode="new" />
        </AppShell>
      </LocaleProvider>,
    );

    const sample = await screen.findByLabelText(
      "Please upload a 10–15-second audio clip of yourself reading a short passage (16-bit WAV, MP3 or M4A; max 10 MB).",
    );
    const voices = sample.closest("section") as HTMLElement;
    expect(
      within(voices).queryByRole("combobox", { name: "Group" }),
    ).toBeNull();
    expect(within(voices).queryByRole("button", { name: "New" })).toBeNull();
    await waitFor(() =>
      expect(api.voiceProfiles).toHaveBeenCalledWith(groupId),
    );
    expect(
      (
        within(screen.getByRole("navigation")).getByRole("button", {
          name: "Done",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(api.enrollVoice).not.toHaveBeenCalled();
    expect(api.createVoicePreview).not.toHaveBeenCalled();
  });

  it("keeps Voice New disabled while group access is unknown, then enables an accessible group", async () => {
    const deniedGroupId = "not-a-member-group";
    const accessibleGroupId = "joined-group";
    let rejectDeniedScope: ((cause: unknown) => void) | null = null;
    const api = {
      workspaceAgents: vi.fn().mockResolvedValue([]),
      chatAgents: vi.fn().mockResolvedValue([]),
      groups: vi.fn().mockResolvedValue([
        { id: deniedGroupId, course_id: courseId, name: "Other group" },
        { id: accessibleGroupId, course_id: courseId, name: "Joined group" },
      ]),
      voiceProfiles: vi.fn().mockImplementation((selectedGroupId: string) => {
        if (selectedGroupId === deniedGroupId) {
          return new Promise((_, reject) => {
            rejectDeniedScope = reject;
          });
        }
        return Promise.resolve([]);
      }),
      enrollVoice: vi.fn(),
      createVoicePreview: vi.fn(),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherStudyformWorkspace initialGroupId={deniedGroupId} />
        </AppShell>
      </LocaleProvider>,
    );

    const heading = await screen.findByRole("heading", {
      name: "Voices",
    });
    const voices = heading.closest("section") as HTMLElement;
    expect(
      within(voices).queryByRole("combobox", { name: "Group" }),
    ).toBeNull();
    const newButton = within(voices).getByRole("button", { name: "New" });
    expect((newButton as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() =>
      expect(api.voiceProfiles).toHaveBeenCalledWith(deniedGroupId),
    );
    await waitFor(() =>
      expect(api.voiceProfiles).toHaveBeenCalledWith(accessibleGroupId),
    );
    await act(async () => {
      rejectDeniedScope?.(
        new PlatformApiError(404, "workspace_member_required"),
      );
      await Promise.resolve();
    });
    await waitFor(() =>
      expect((newButton as HTMLButtonElement).disabled).toBe(false),
    );
    expect(within(voices).queryByRole("alert")).toBeNull();
    expect(screen.getByText("No voices yet.")).toBeTruthy();
    expect(api.enrollVoice).not.toHaveBeenCalled();
  });

  it("does not treat a Voice profile server error as a confirmed scope denial", async () => {
    const groupId = "teacher-group";
    const api = {
      workspaceAgents: vi.fn().mockResolvedValue([]),
      chatAgents: vi.fn().mockResolvedValue([]),
      groups: vi
        .fn()
        .mockResolvedValue([
          { id: groupId, course_id: courseId, name: "Group" },
        ]),
      voiceProfiles: vi
        .fn()
        .mockRejectedValue(new PlatformApiError(500, "temporary_failure")),
      enrollVoice: vi.fn(),
      createVoicePreview: vi.fn(),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherStudyformWorkspace initialGroupId={groupId} />
        </AppShell>
      </LocaleProvider>,
    );

    const heading = await screen.findByRole("heading", {
      name: "Voices",
    });
    const voices = heading.closest("section") as HTMLElement;
    const newButton = await within(voices).findByRole("button", {
      name: "New",
    });
    await waitFor(() =>
      expect(api.voiceProfiles).toHaveBeenCalledWith(groupId),
    );
    await waitFor(() =>
      expect((newButton as HTMLButtonElement).disabled).toBe(false),
    );
    expect(within(voices).getByRole("alert")).toBeTruthy();
  });

  it("keeps direct Voice New Done disabled when its selected group returns 404", async () => {
    const groupId = "not-a-member-group";
    const api = {
      workspaceAgents: vi.fn().mockResolvedValue([]),
      chatAgents: vi.fn().mockResolvedValue([]),
      groups: vi
        .fn()
        .mockResolvedValue([
          { id: groupId, course_id: courseId, name: "Group" },
        ]),
      voiceProfiles: vi
        .fn()
        .mockRejectedValue(
          new PlatformApiError(404, "workspace_member_required"),
        ),
      enrollVoice: vi.fn(),
      createVoicePreview: vi.fn(),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherStudyformWorkspace
            initialGroupId={groupId}
            initialMode="new"
          />
        </AppShell>
      </LocaleProvider>,
    );

    const sampleInput = await screen.findByLabelText(
      "Please upload a 10–15-second audio clip of yourself reading a short passage (16-bit WAV, MP3 or M4A; max 10 MB).",
    );
    const voices = sampleInput.closest("section") as HTMLElement;
    await waitFor(() =>
      expect(api.voiceProfiles).toHaveBeenCalledWith(groupId),
    );
    expect(within(voices).queryByRole("alert")).toBeNull();
    expect(
      (
        within(screen.getByRole("navigation")).getByRole("button", {
          name: "Done",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(api.enrollVoice).not.toHaveBeenCalled();
    expect(
      within(voices).queryByRole("combobox", { name: "Group" }),
    ).toBeNull();
  });

  it("lets the owner share a private source and personal Agent from the workbench", async () => {
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

    const visibilityHeading = await screen.findByRole("heading", {
      name: "Visibility",
    });
    const visibilitySection = visibilityHeading.closest(
      "section",
    ) as HTMLElement;
    expect(
      within(visibilitySection).getByText("Private", { exact: true }),
    ).toBeTruthy();
    expect(visibilityHeading.getAttribute("data-ui-guide")).toBe(
      "agent.visibility",
    );
    expect(
      within(visibilitySection).queryByText(
        "Shareable; students need an explicit grant",
      ),
    ).toBeNull();
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
