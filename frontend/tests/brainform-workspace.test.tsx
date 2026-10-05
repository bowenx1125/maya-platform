import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useState, type ReactNode } from "react";

const state = vi.hoisted(() => ({
  api: {} as Record<string, ReturnType<typeof vi.fn>>,
  role: "student",
  routerPush: vi.fn(),
  userId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    identityGeneration: 1,
    user: {
      id: state.userId,
      courses: [{ course_id: "course-1", role: state.role }],
      groups: [],
    },
  }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.routerPush }),
}));

import { BrainformWorkspace } from "../components/knowledge/brainform-workspace";
import { LocaleProvider } from "../components/locale";
import {
  WorkspaceActionsContext,
  type WorkspaceActions,
} from "../components/workspace-actions";

function ActionsHost({ children }: { children: ReactNode }) {
  const [actions, setActions] = useState<WorkspaceActions>({});
  return (
    <WorkspaceActionsContext.Provider value={setActions}>
      <button onClick={actions.new?.onClick} disabled={actions.new?.disabled}>
        New
      </button>
      {children}
    </WorkspaceActionsContext.Provider>
  );
}

function renderWithActions() {
  return render(
    <LocaleProvider initialLocale="en">
      <ActionsHost>
        <BrainformWorkspace role="teacher" />
      </ActionsHost>
    </LocaleProvider>,
  );
}

function markdownUpload(name: string, bytes: Promise<ArrayBuffer>) {
  const file = new File([], name, { type: "text/markdown" });
  Object.defineProperty(file, "arrayBuffer", { value: () => bytes });
  return file;
}

const agent = {
  agent_id: "agent-1",
  version_id: "agent-version-1",
  course_id: "course-1",
  name: "Socrates",
  version_label: "V1",
  avatar_config: {},
  available: true,
};
const source = {
  id: "document-1",
  group_id: null,
  course_id: "course-1",
  ownership_scope: "personal",
  visibility: "private",
  can_manage_visibility: true,
  source_filename: "lesson.md",
  char_count: 18,
  authorization_epoch: 1,
  content_hash: "a".repeat(64),
  index_revision: 4,
  index_status: "ready",
  workspace_state: "active",
  safe_error_code: null,
  created_at: "2026-10-04T00:00:00Z",
};

function renderWorkspace(role = state.role) {
  return render(
    <LocaleProvider initialLocale="en">
      <BrainformWorkspace role={role as "teacher" | "student"} />
    </LocaleProvider>,
  );
}

beforeEach(() => {
  state.role = "student";
  state.userId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  state.routerPush.mockClear();
  sessionStorage.clear();
  state.api = {
    courses: vi
      .fn()
      .mockResolvedValue([{ id: "course-1", name: "Course One" }]),
    groups: vi.fn().mockResolvedValue([]),
    group: vi.fn().mockResolvedValue({
      id: "group-1",
      course_id: "course-1",
      name: "Group",
    }),
    knowledge: vi.fn().mockResolvedValue([]),
    knowledgeSet: vi.fn().mockResolvedValue({
      id: "set-1",
      metadata_revision: 0,
    }),
    updateKnowledgeSet: vi.fn().mockResolvedValue({
      id: "set-1",
      display_name: "Renamed Knowledge",
      metadata_revision: 1,
    }),
    workspaceDocuments: vi.fn().mockResolvedValue([]),
    brainformKnowledge: vi.fn().mockResolvedValue([]),
    chatAgents: vi.fn().mockResolvedValue([agent]),
    teams: vi.fn().mockResolvedValue([]),
    mayaTeams: vi.fn().mockResolvedValue([]),
    downloadKnowledge: vi.fn().mockResolvedValue({
      filename: "lesson.md",
      content: "# Source\n\nSame text.",
    }),
    renameKnowledgeDocument: vi
      .fn()
      .mockResolvedValue({ ...source, source_filename: "renamed.md" }),
    replaceKnowledgeDocument: vi.fn(),
    regenerateKnowledgeMarkdown: vi.fn().mockResolvedValue({
      action_id: "11111111-1111-4111-8111-111111111111",
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      run_id: "run-1",
      job_id: "job-1",
      state: "pending",
    }),
    knowledgeGenerationJob: vi.fn().mockResolvedValue({
      run_id: "run-1",
      job_id: "job-1",
      knowledge_set_id: "set-1",
      state: "blocked",
      provider_manifest_hash: "a".repeat(64),
      safe_error_code: "provider_confirmation_required",
      accepted_item_count: 0,
      materialized_item_count: 0,
      failed_item_count: 0,
      created_at: "2026-10-04T00:00:00Z",
      updated_at: "2026-10-04T00:00:00Z",
    }),
    knowledgeMarkdown: vi.fn().mockResolvedValue({
      audience: "full",
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      version_seq: 1,
      content_hash: "b".repeat(64),
      markdown: "# Canonical body\n\nThe current Agent document.",
      projection_available: true,
      can_read: true,
      can_edit: false,
      created_at: "2026-10-04T00:00:00Z",
    }),
    saveKnowledgeMarkdown: vi.fn(),
    createWorkspaceKnowledge: vi.fn().mockResolvedValue({ document: source }),
  };
});

afterEach(() => cleanup());

describe("Brainform workspace actions", () => {
  it("imports Markdown into a draft and saves its full Unicode text through the existing RAG API", async () => {
    state.role = "teacher";
    renderWithActions();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    const markdown = "# 课程\n\n保留原始资料。\n";
    const file = markdownUpload(
      "lecture.md",
      Promise.resolve(new TextEncoder().encode(markdown).buffer),
    );
    const input = screen.getByLabelText("Import a file");
    expect(input.getAttribute("accept")).toBe(".md,text/markdown");
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => {
      const content = screen.getByRole("textbox", {
        name: "Markdown content",
      }) as HTMLTextAreaElement;
      expect(content.value).toBe(markdown);
    });
    expect(state.api.createWorkspaceKnowledge).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(state.api.createWorkspaceKnowledge).toHaveBeenCalledTimes(1),
    );
    const [courseId, savedFile, options] =
      state.api.createWorkspaceKnowledge.mock.calls[0];
    expect(courseId).toBe("course-1");
    expect(savedFile.name).toBe("lecture.md");
    expect(options.idempotency).toBeTruthy();
    const savedText = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(savedFile);
    });
    expect(savedText).toBe(markdown);
    expect(state.api.regenerateKnowledgeMarkdown).not.toHaveBeenCalled();
  });

  it("keeps an existing draft when an imported file has invalid UTF-8 or is not Markdown", async () => {
    state.role = "teacher";
    renderWithActions();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    const content = screen.getByRole("textbox", { name: "Markdown content" });
    fireEvent.change(content, { target: { value: "# Keep my draft" } });
    const malformed = markdownUpload(
      "broken.md",
      Promise.resolve(new Uint8Array([0xc3, 0x28]).buffer),
    );
    fireEvent.change(screen.getByLabelText("Import a file"), {
      target: { files: [malformed] },
    });
    await waitFor(() =>
      expect(
        screen.getByLabelText("Import a file").hasAttribute("disabled"),
      ).toBe(false),
    );
    expect(screen.getByDisplayValue("# Keep my draft")).toBeTruthy();
    expect(screen.getByDisplayValue("notes.md")).toBeTruthy();
    const pdf = markdownUpload(
      "wrong.pdf",
      Promise.resolve(new ArrayBuffer(0)),
    );
    fireEvent.change(screen.getByLabelText("Import a file"), {
      target: { files: [pdf] },
    });
    expect(screen.getByDisplayValue("# Keep my draft")).toBeTruthy();
    expect(state.api.createWorkspaceKnowledge).not.toHaveBeenCalled();
  });

  it("does not overwrite a newer RAG draft when an older file read finishes late", async () => {
    state.role = "teacher";
    renderWithActions();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    let finish!: (bytes: ArrayBuffer) => void;
    const bytes = new Promise<ArrayBuffer>((resolve) => {
      finish = resolve;
    });
    fireEvent.change(screen.getByLabelText("Import a file"), {
      target: { files: [markdownUpload("late.md", bytes)] },
    });
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Markdown content" }),
      { target: { value: "# New draft" } },
    );
    finish(new TextEncoder().encode("# Old file").buffer);
    await bytes;
    await waitFor(() =>
      expect(screen.getByDisplayValue("# New draft")).toBeTruthy(),
    );
    expect(screen.getByDisplayValue("notes.md")).toBeTruthy();
    expect(screen.queryByDisplayValue("late.md")).toBeNull();
    expect(state.api.createWorkspaceKnowledge).not.toHaveBeenCalled();
  });

  it("navigates to the current role's Agent Chat with a fresh durable Memory intent", async () => {
    renderWorkspace();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open Socrates memory in Chats",
      }),
    );
    expect(state.routerPush).toHaveBeenCalledTimes(1);
    const destination = new URL(
      String(state.routerPush.mock.calls[0][0]),
      "https://maya.test",
    );
    expect(destination.pathname).toBe("/student/chat");
    expect(destination.searchParams.get("memory_actor_id")).toBe(state.userId);
    expect(destination.searchParams.get("memory_course_id")).toBe("course-1");
    expect(destination.searchParams.get("memory_source_kind")).toBe("agent");
    expect(destination.searchParams.get("memory_source_id")).toBe("agent-1");
    expect(destination.searchParams.get("memory_action_id")).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
  });

  it("uses metadata rename for a filename-only edit and leaves source replacement untouched", async () => {
    state.role = "teacher";
    state.userId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
    state.api.workspaceDocuments.mockResolvedValue([source]);
    renderWorkspace("teacher");

    const editButtons = await screen.findAllByRole("button", {
      name: "Edit lesson.md",
    });
    fireEvent.click(editButtons[0]);
    const filename = await screen.findByDisplayValue("lesson.md");
    fireEvent.change(filename, { target: { value: "renamed.md" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(state.api.renameKnowledgeDocument).toHaveBeenCalledTimes(1),
    );
    expect(state.api.renameKnowledgeDocument).toHaveBeenCalledWith(
      "document-1",
      { expected_filename: "lesson.md", filename: "renamed.md" },
      expect.objectContaining({ idempotency: expect.any(Object) }),
    );
    expect(state.api.replaceKnowledgeDocument).not.toHaveBeenCalled();
  });

  it("recovers the owner-only disclosure for the queued generation instead of starting another run", async () => {
    state.role = "teacher";
    state.userId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
    sessionStorage.setItem(
      'maya:brainform-generation-job:["cccccccc-cccc-4ccc-8ccc-cccccccccccc","teacher","course-1"]:set-1',
      "job-1",
    );
    state.api.brainformKnowledge.mockResolvedValue([
      {
        agent_id: "agent-1",
        canonical_set_id: "set-1",
        source_agent_display_name: "Socrates",
        knowledge_display_name: "Socrates",
        can_read: true,
        can_edit: true,
        version_seq: null,
        content_hash: null,
        generation_state: "failed",
        safe_error_code: "provider_confirmation_required",
      },
    ]);
    renderWorkspace("teacher");

    const recovery = await screen.findByRole("link", {
      name: "Open provider disclosure",
    });
    expect(recovery.getAttribute("href")).toBe(
      `/teacher/provider-disclosures/${"a".repeat(64)}`,
    );
    expect(state.api.regenerateKnowledgeMarkdown).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(state.api.knowledgeGenerationJob).toHaveBeenCalledWith("job-1"),
    );
  });

  it("opens the same canonical Markdown document from an Agent-specific entry", async () => {
    state.api.brainformKnowledge.mockResolvedValue([
      {
        agent_id: "agent-1",
        canonical_set_id: "set-1",
        source_agent_display_name: "Socrates",
        knowledge_display_name: "Socrates Knowledge",
        can_read: true,
        can_edit: false,
        version_seq: 1,
        content_hash: "b".repeat(64),
        generation_state: "completed",
        safe_error_code: null,
      },
    ]);

    render(<BrainformWorkspace role="student" initialAgentId="agent-1" />);

    expect(await screen.findByText("The current Agent document.")).toBeTruthy();
    expect(state.api.knowledgeMarkdown).toHaveBeenCalledWith("set-1");
  });

  it("keeps metadata-only title rename available while Knowledge is generating", async () => {
    state.role = "teacher";
    state.userId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
    state.api.brainformKnowledge.mockResolvedValue([
      {
        agent_id: "agent-1",
        canonical_set_id: "set-1",
        source_agent_display_name: "Socrates",
        knowledge_display_name: "Socrates Knowledge",
        can_read: true,
        can_edit: true,
        version_seq: 1,
        content_hash: "b".repeat(64),
        generation_state: "running",
        safe_error_code: null,
      },
    ]);

    renderWorkspace("teacher");

    fireEvent.click(
      await screen.findByRole("button", { name: "Rename Socrates Knowledge" }),
    );
    const title = await screen.findByRole("textbox", {
      name: "Knowledge title",
    });
    fireEvent.change(title, { target: { value: "Renamed Knowledge" } });
    fireEvent.blur(title);

    await waitFor(() =>
      expect(state.api.updateKnowledgeSet).toHaveBeenCalledWith(
        "set-1",
        {
          expected_metadata_revision: 0,
          display_name: "Renamed Knowledge",
        },
        expect.anything(),
      ),
    );
  });

  it("renders a safe read-only graph from the current canonical Markdown", async () => {
    state.api.brainformKnowledge.mockResolvedValue([
      {
        agent_id: "agent-1",
        canonical_set_id: "set-1",
        source_agent_display_name: "Socrates",
        knowledge_display_name: "Socrates Knowledge",
        can_read: true,
        can_edit: false,
        version_seq: 1,
        content_hash: "b".repeat(64),
        generation_state: "completed",
        safe_error_code: null,
      },
    ]);
    state.api.knowledgeMarkdown.mockResolvedValue({
      audience: "student",
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      version_seq: 1,
      content_hash: "b".repeat(64),
      markdown: "# Canonical\n\n## Graph\n\n- Seasonal cycle → Tilted axis",
      projection_available: true,
      can_read: true,
      can_edit: false,
      created_at: "2026-10-04T00:00:00Z",
    });

    render(<BrainformWorkspace role="student" initialAgentId="agent-1" />);

    expect(
      await screen.findByRole("img", { name: /Knowledge relationship graph/ }),
    ).toBeTruthy();
    expect(screen.getByText("Seasonal cycle")).toBeTruthy();
    expect(screen.getByText("Tilted axis")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Graph" })).toBeNull();
  });

  it("keeps an unparseable Graph section as safe Markdown text", async () => {
    state.api.brainformKnowledge.mockResolvedValue([
      {
        agent_id: "agent-1",
        canonical_set_id: "set-1",
        source_agent_display_name: "Socrates",
        knowledge_display_name: "Socrates Knowledge",
        can_read: true,
        can_edit: false,
        version_seq: 1,
        content_hash: "b".repeat(64),
        generation_state: "completed",
        safe_error_code: null,
      },
    ]);
    state.api.knowledgeMarkdown.mockResolvedValue({
      audience: "student",
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      version_seq: 1,
      content_hash: "b".repeat(64),
      markdown: "# Canonical\n\n## Graph\n\nA custom map cannot be parsed yet.",
      projection_available: true,
      can_read: true,
      can_edit: false,
      created_at: "2026-10-04T00:00:00Z",
    });

    render(<BrainformWorkspace role="student" initialAgentId="agent-1" />);

    expect(
      await screen.findByText("A custom map cannot be parsed yet."),
    ).toBeTruthy();
    expect(
      screen.queryByRole("img", { name: /Knowledge relationship graph/ }),
    ).toBeNull();
  });
});
