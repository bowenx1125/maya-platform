import "@testing-library/jest-dom/vitest";

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
import { buildAgentTemplate } from "../components/agent-template";
import { AppShell } from "../components/app-shell";
import {
  TeacherDashboard,
  TeacherPersonalAgentCreate,
  TeacherStudyformWorkspace,
} from "../components/teacher-workspace";
import { VoicesPage } from "../components/voice/voices-page";
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

function expectFooterAfter(control: HTMLElement, content: HTMLElement) {
  expect(control.closest(".section-card-header")).toBeNull();
  expect(control.closest("section")).toBe(content.closest("section"));
  expect(
    content.compareDocumentPosition(control) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
}

function expectMarkdownFooter(markdown: string) {
  const editor = screen.getByRole("textbox", { name: "AGENT.md editor" });
  const card = editor.closest("section")!;
  const count = within(card).getByText(
    `${markdown.length.toLocaleString()} characters`,
  );
  expect(count.closest(".editor-footer")).toBeTruthy();
  const template = within(card).getByRole("button", { name: "Template" });
  const download = within(card).getByRole("button", {
    name: "Download AGENT.md",
  });
  const upload = within(card).getByLabelText("Upload");
  const uploadLabel = upload.closest("label")!;
  for (const [control, label] of [
    [template, "Template"],
    [download, "Download"],
    [uploadLabel, "Upload"],
  ] as const) {
    expect(within(control).getByText(label)).toBeVisible();
    expect(control.querySelector('svg[aria-hidden="true"]')).toBeTruthy();
    expectFooterAfter(control, editor);
    expectFooterAfter(control, count);
  }
  expect(download).toHaveAttribute("data-ui-guide", "agent.download");
  expect(uploadLabel).toHaveAttribute("data-ui-guide", "agent.uploadMarkdown");
  expect(upload).toHaveAttribute("accept", ".md,text/markdown");
  return { editor, template, download, upload };
}

describe("W1 teacher personal workspace", () => {
  it("keeps create card actions below their content and preserves the Name controls", async () => {
    const api = {
      workspaceDocuments: vi.fn().mockResolvedValue([]),
      knowledgeSets: vi.fn().mockResolvedValue([]),
      avatarTemplates: vi.fn().mockResolvedValue([]),
      personalVoiceProfiles: vi.fn().mockResolvedValue([]),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(<TeacherPersonalAgentCreate />);
    await screen.findByRole("radio", { name: "None" });

    const { editor, template, download } = expectMarkdownFooter("");
    expect(download).toBeDisabled();
    fireEvent.change(editor, { target: { value: "# Notes" } });
    expect(download).toBeEnabled();
    expectMarkdownFooter("# Notes");
    fireEvent.change(editor, { target: { value: "" } });
    expect(download).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Teacher Lens" },
    });
    fireEvent.click(template);
    expect(editor).toHaveValue(buildAgentTemplate("Teacher Lens"));
    expect(download).toBeEnabled();

    const name = screen.getByRole("textbox", { name: "Name" });
    for (const label of ["Private", "Public"]) {
      expectFooterAfter(screen.getByRole("button", { name: label }), name);
    }
    const ragUpload = screen.getByLabelText("Upload RAG");
    const ragNew = ragUpload.closest("label")!;
    const empty = screen.getByText("No RAG yet.");
    expect(empty).toHaveClass("muted-copy");
    expect(empty.tagName).toBe("P");
    expectFooterAfter(ragNew, empty);
    expect(ragNew).toHaveAttribute("data-ui-guide", "agent.uploadRag");
    expect(within(ragNew).getByText("New")).toBeVisible();
    fireEvent.change(ragUpload, {
      target: { files: [new File(["# Source"], "queued.md")] },
    });
    const queued = await screen.findByRole("checkbox", { name: "queued.md" });
    expectFooterAfter(ragNew, queued);
    expect(screen.queryByText("No RAG yet.")).toBeNull();

    const picker = screen.getByRole("radiogroup", { name: "Voices" });
    const voiceCard = picker.closest("section")!;
    const voiceNew = within(voiceCard).getByRole("button", { name: "New" });
    expectFooterAfter(voiceNew, picker);
    expect(screen.getByRole("radio", { name: "None" })).toBeChecked();
  });

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
      <>
        <AppShell role="teacher">
          <TeacherStudyformWorkspace view="agents" />
        </AppShell>
      </>,
    );

    const tile = await screen.findByRole("link", { name: "Teacher Lens" });
    expect(tile.getAttribute("href")).toBe(`/teacher/agents/${agentId}`);
    expect(screen.getByText("V1.0")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete" })).toBeTruthy();
    expect(api.publishedAgents).toHaveBeenCalledWith(courseId);
    expect(
      screen.getByRole("link", { name: "Agents" }).getAttribute("href"),
    ).toBe("/teacher/agents");
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
      <>
        <AppShell role="teacher">
          <TeacherStudyformWorkspace view="agents" />
        </AppShell>
      </>,
    );

    const tile = await screen.findByRole("link", { name: "Teacher Lens" });
    expect(tile.getAttribute("href")).toBe(`/teacher/agents/${agentId}`);
    expect(screen.queryByText("Draft")).toBeNull();
    expect(api.workspaceAgents).toHaveBeenCalledWith(courseId);
  });

  it("shows published Agents on Home without a Delete", async () => {
    // Home reads the class; deleting an Agent lives on Studyform.
    const tile = (id: string, name: string, canDelete: boolean) => ({
      agent: personalAgent({
        id,
        name,
        group_id: "group-1",
        ownership_scope: "group",
        visibility: "public",
        can_edit: canDelete,
        can_delete: canDelete,
        current_published_version_id: `${id}-v`,
      }),
      author: { user_id: "student-1", display_name: "Bowen", avatar: null },
      current_version: { ...draft(privateDocument()), id: `${id}-v` },
      group_name: "Group 1",
    });
    const api = {
      publishedAgents: vi
        .fn()
        .mockResolvedValue([
          tile("student", "Student Lens", true),
          tile("locked", "Locked Lens", false),
        ]),
      groups: vi.fn().mockResolvedValue([]),
      deleteAgent: vi.fn(),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <>
        <TeacherDashboard />
      </>,
    );
    await screen.findByRole("link", { name: "Student Lens" });
    const student = document.querySelector('[data-agent-card="student"]')!;
    expect(screen.getByRole("link", { name: "Locked Lens" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(within(student as HTMLElement).getByText("V1.0")).toBeTruthy();
  });

  it("counts the course's active students on Home", async () => {
    const api = {
      publishedAgents: vi.fn().mockResolvedValue([]),
      groups: vi.fn().mockResolvedValue([]),
      courseRoster: vi.fn().mockResolvedValue({
        entries: [
          { user_id: "a", role: "student", status: "active" },
          { user_id: "b", role: "student", status: "active" },
          { user_id: "c", role: "student", status: "inactive" },
          { user_id: "d", role: "teacher", status: "active" },
        ],
      }),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <>
        <TeacherDashboard />
      </>,
    );
    const label = await screen.findByText("Students");
    await waitFor(() =>
      expect(label.closest(".home-stat")?.textContent).toMatch(/^2/),
    );
    expect(api.courseRoster).toHaveBeenCalledWith(courseId);
  });

  it("shows Delete on Studyform for a student's public Agent with can_delete", async () => {
    const studentAgent = {
      agent: personalAgent({
        id: "student",
        name: "Student Lens",
        group_id: "group-1",
        ownership_scope: "group",
        visibility: "public",
        can_edit: true,
        can_delete: true,
        current_published_version_id: "student-v",
        current_draft_version_id: null,
      }),
      author: { user_id: "student-1", display_name: "Bowen", avatar: null },
      current_version: {
        id: "student-v",
        version_label: "V1.0",
        state: "published",
      },
      group_name: "Group 1",
    };
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const api = {
      publishedAgents: vi.fn().mockResolvedValue([studentAgent]),
      chatAgents: vi.fn().mockResolvedValue([]),
      groups: vi.fn().mockResolvedValue([]),
      deleteAgent: vi.fn().mockResolvedValue(undefined),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <>
        <AppShell role="teacher">
          <TeacherStudyformWorkspace view="agents" />
        </AppShell>
      </>,
    );
    await screen.findByRole("link", { name: "Student Lens" });
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(api.deleteAgent).toHaveBeenCalledWith("student"),
    );
  });

  it("shows the colleague Home with the teacher's own workspace Agents", async () => {
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
      <>
        <TeacherDashboard />
      </>,
    );

    await screen.findByRole("heading", { name: /Welcome/ });
    await waitFor(() =>
      expect(api.workspaceAgents).toHaveBeenCalledWith(courseId),
    );
    expect(screen.queryByText("Personal Agents · 0")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Guide" })).toBeNull();
    // Both agent lists are empty. That is not a card: the legacy empty
    // state ("No Agents yet." with the diamond mark) does not belong here.
    expect(screen.queryByText("No Agents yet.")).toBeNull();
    expect(document.querySelector(".empty-card")).toBeNull();
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
      <>
        <AppShell role="teacher">
          <TeacherPersonalAgentCreate />
        </AppShell>
      </>,
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

  // A new Agent must not offer another Agent's private RAG.
  it("offers a new Agent only library RAG and no Knowledge controls", async () => {
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
          owner_username: "kaikai",
          used_by_agents: [
            { agent_id: "agent-socrates", name: "Socrates" },
            { agent_id: "agent-plato", name: "Plato" },
          ],
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
      <>
        <AppShell role="teacher">
          <TeacherPersonalAgentCreate />
        </AppShell>
      </>,
    );

    const shared = await screen.findByRole("checkbox", {
      name: "shared-notes.md",
    });
    // Two files can share a name (each Agent's own baseline.md); the row
    // says who uploaded it and which Agents use it.
    expect(shared.getAttribute("aria-describedby")).toBe(
      "rag-origin-shared-source",
    );
    expect(
      document.getElementById("rag-origin-shared-source")?.textContent,
    ).toBe("@kaikai · Used by Socrates, Plato");
    expect(
      screen.queryByRole("checkbox", { name: "Live Knowledge" }),
    ).toBeNull();
    expect(
      screen.queryByRole("checkbox", { name: "private-notes.md" }),
    ).toBeNull();
    expect(
      screen.queryByRole("checkbox", { name: "Deleted Agent Knowledge" }),
    ).toBeNull();
  });

  // Owner decision (2026-10-12): a teacher creates personal voices that only
  // that teacher may choose; the Voices page lists those, never a group's.
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
      knowledge: vi.fn().mockResolvedValue([]),
      workspaceDocuments: vi.fn().mockResolvedValue([]),
      brainformKnowledge: vi.fn().mockResolvedValue([]),
      teams: vi.fn().mockResolvedValue([]),
      mayaTeams: vi.fn().mockResolvedValue([]),
      courseAssessmentAttempts: vi.fn().mockResolvedValue([]),
      courses: vi.fn().mockResolvedValue([]),
    };
    mockedUseSession.mockReturnValue(
      teacherSession(api, [{ group_id: "teacher-group" }]),
    );
    render(
      <>
        <AppShell role="teacher">
          <VoicesPage role="teacher" />
        </AppShell>
      </>,
    );

    const heading = await screen.findByRole("heading", { name: "Voices" });
    const voices = heading.closest("section") ?? heading.parentElement;
    expect(
      await within(voices as HTMLElement).findByText("teacher-voice.wav"),
    ).toBeTruthy();
    expect(
      within(voices as HTMLElement).getByRole("button", { name: "Preview" }),
    ).toBeTruthy();
    expect(api.personalVoiceProfiles).toHaveBeenCalledWith(courseId);
    expect(api.voiceProfiles).not.toHaveBeenCalled();
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
      <>
        <AppShell role="teacher">
          <VoicesPage role="teacher" />
        </AppShell>
      </>,
    );

    await screen.findByRole("heading", { name: "Voices" });
    await waitFor(() =>
      expect(api.personalVoiceProfiles).toHaveBeenCalledWith(courseId),
    );
    // Errors are spoken by the mascot: the alert floats in the tray.
    expect((await screen.findAllByRole("alert")).length).toBeGreaterThan(0);
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
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <>
        <AgentWorkbench
          key="teacher-scope"
          actorScopeKey="teacher-user:teacher-course:2"
          backHref="/teacher"
          versionId={versionId}
        />
      </>,
    );

    expect(
      await screen.findByRole("checkbox", { name: "private-notes.md" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Share source/ })).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Make source private/ }),
    ).toBeNull();
    expect(screen.queryByText("Ready")).toBeNull();
    // The RAG list has no per-file visibility control. (The Agent's own
    // Private / Public switch lives on its Name card, outside this list.)
    const ragList = screen
      .getByRole("checkbox", { name: "private-notes.md" })
      .closest("ul, ol, fieldset, section") as HTMLElement;
    expect(
      within(ragList).queryByRole("group", { name: "Visibility" }),
    ).toBeNull();
    expect(screen.getAllByRole("group", { name: "Visibility" })).toHaveLength(
      1,
    );
    expect(
      screen.queryByText("Shareable; students need an explicit grant"),
    ).toBeNull();
  });
});

// Owner 2026-11-08: the Name card owns the name and the one-way Private →
// Public switch; AGENT.md no longer renames the Agent.
describe("Agent Name card", () => {
  function editorApi(agentOverrides: Partial<AgentDetail> = {}) {
    let agent = personalAgent(agentOverrides);
    const document = privateDocument();
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
      updateAgentMetadata: vi.fn(async (_id: string, body: object) => {
        agent = {
          ...agent,
          ...body,
          metadata_revision: agent.metadata_revision + 1,
        } as AgentDetail;
        return agent;
      }),
      uploadAgentMd: vi.fn(async () => ({
        ...currentDraft,
        agent_md: "# Uploaded Agent",
      })),
      uploadWorkspaceKnowledge: vi.fn(async () => ({
        agent_version: currentDraft,
        document: {
          ...document,
          id: "uploaded-source",
          source_filename: "uploaded.md",
        },
      })),
      publish: vi.fn(async () => ({ ...currentDraft, state: "published" })),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <AgentWorkbench
        key="teacher-scope"
        actorScopeKey="teacher-user:teacher-course:2"
        backHref="/teacher"
        versionId={versionId}
      />,
    );
    return api;
  }

  it("keeps edit Markdown and RAG footer uploads functional below the sticker list", async () => {
    const api = editorApi();
    await screen.findByRole("checkbox", { name: "private-notes.md" });
    const { editor, download, upload } = expectMarkdownFooter(
      draft(privateDocument()).agent_md!,
    );
    expect(download).toBeEnabled();
    fireEvent.change(editor, { target: { value: "" } });
    expect(download).toBeDisabled();
    const markdownFile = new File(["# Uploaded Agent"], "AGENT.md", {
      type: "text/markdown",
    });
    fireEvent.change(upload, { target: { files: [markdownFile] } });
    await waitFor(() => expect(editor).toHaveValue("# Uploaded Agent"));
    expect(api.uploadAgentMd).toHaveBeenCalledWith(versionId, markdownFile, 0);
    expectMarkdownFooter("# Uploaded Agent");
    expect(download).toBeEnabled();

    const ragUpload = screen.getByLabelText("Upload RAG");
    const ragNew = ragUpload.closest("label")!;
    const rag = screen.getByRole("group", { name: "RAG" });
    expectFooterAfter(ragNew, rag);
    expect(ragNew).toHaveAttribute("data-ui-guide", "agent.uploadRag");
    expect(within(rag).getByRole("button", { name: /View/ })).toBeVisible();
    expect(within(rag).getByRole("button", { name: /Download/ })).toBeVisible();
    const source = new File(["# Source"], "uploaded.md", {
      type: "text/markdown",
    });
    fireEvent.change(ragUpload, { target: { files: [source] } });
    const uploaded = await screen.findByRole("checkbox", {
      name: "uploaded.md",
    });
    expectFooterAfter(ragNew, uploaded);
    expect(api.uploadWorkspaceKnowledge).toHaveBeenCalledWith(
      courseId,
      versionId,
      source,
      0,
      expect.objectContaining({ idempotency: expect.any(Object) }),
    );
    const name = screen.getByRole("textbox", { name: "Name" });
    for (const label of ["Private", "Public"]) {
      expectFooterAfter(screen.getByRole("button", { name: label }), name);
    }
  });

  it("makes a private Agent public once, after a confirm", async () => {
    const api = editorApi({
      is_creator: true,
      can_manage_visibility: true,
      visibility: "private",
    });
    const group = await screen.findByRole("group", { name: "Visibility" });
    const makePublic = within(group).getByRole("button", { name: "Public" });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    fireEvent.click(makePublic);
    expect(api.updateAgentMetadata).not.toHaveBeenCalled();
    confirm.mockReturnValueOnce(true);
    fireEvent.click(makePublic);
    await waitFor(() =>
      expect(api.updateAgentMetadata).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ visibility: "public" }),
      ),
    );
    // Then Done's publish makes the new public version.
    await waitFor(() => expect(api.publish).toHaveBeenCalled());
    expect(api.updateAgentMetadata.mock.invocationCallOrder[0]).toBeLessThan(
      api.publish.mock.invocationCallOrder[0],
    );
    confirm.mockRestore();
  });

  it("keeps a public Agent public and follows edit permission for Private", async () => {
    editorApi({
      is_creator: true,
      can_manage_visibility: true,
      visibility: "public",
    });
    const shared = await screen.findByRole("group", { name: "Visibility" });
    const back = within(shared).getByRole("button", {
      name: "Private",
    }) as HTMLButtonElement;
    expect(back.disabled).toBe(true);
    expect(back.title).toBe("A public Agent stays public.");
    cleanup();
    editorApi({
      is_creator: false,
      can_manage_visibility: true,
      visibility: "private",
    });
    const editor = await screen.findByRole("group", { name: "Visibility" });
    expect(
      (
        within(editor).getByRole("button", {
          name: "Public",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
    cleanup();
    editorApi({
      is_creator: false,
      can_manage_visibility: false,
      visibility: "private",
    });
    const group = await screen.findByRole("group", { name: "Visibility" });
    expect(
      (
        within(group).getByRole("button", {
          name: "Public",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  it("shows the Agent's name on its card for renaming", async () => {
    editorApi({ name: "Laozi" });
    const name = (await screen.findByRole("textbox", {
      name: "Name",
    })) as HTMLInputElement;
    expect(name.value).toBe("Laozi");
    fireEvent.change(name, { target: { value: "Laozi 2" } });
    expect(name.value).toBe("Laozi 2");
  });
});

describe("Agent Name card · rename alone", () => {
  it("lets Done save a new name without publishing a version", async () => {
    const agent = personalAgent({ name: "Laozi", is_creator: true });
    const document = privateDocument();
    const currentDraft = draft(document);
    const api = {
      version: vi.fn().mockResolvedValue(currentDraft),
      agent: vi.fn().mockResolvedValue(agent),
      workspaceDocuments: vi.fn().mockResolvedValue([document]),
      knowledgeSets: vi.fn().mockResolvedValue([]),
      agentKnowledgeSets: vi.fn().mockResolvedValue({
        agent_id: agent.id,
        agent_metadata_revision: agent.metadata_revision,
        sets: [],
      }),
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
      updateAgentMetadata: vi.fn(async () => ({
        ...agent,
        name: "Laozi Elder",
      })),
      publish: vi.fn(),
    };
    mockedUseSession.mockReturnValue(teacherSession(api));
    render(
      <AgentWorkbench
        key="teacher-scope"
        actorScopeKey="teacher-user:teacher-course:2"
        backHref="/teacher"
        versionId={versionId}
      />,
    );
    const name = await screen.findByRole("textbox", { name: "Name" });
    fireEvent.change(name, { target: { value: "Laozi Elder" } });
    const done = screen.getByRole("button", {
      name: "Done",
    }) as HTMLButtonElement;
    await waitFor(() => expect(done.disabled).toBe(false));
    fireEvent.click(done);
    await waitFor(() =>
      expect(api.updateAgentMetadata).toHaveBeenCalledWith(
        agent.id,
        expect.objectContaining({ name: "Laozi Elder" }),
      ),
    );
    expect(await screen.findByText("Name saved.")).toBeTruthy();
    expect(api.publish).not.toHaveBeenCalled();
  });
});
