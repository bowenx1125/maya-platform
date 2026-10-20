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
import { useMemo, useState, type ComponentProps, type ReactNode } from "react";

const state = vi.hoisted(() => ({
  api: {} as Record<string, ReturnType<typeof vi.fn>>,
  role: "student",
  routerPush: vi.fn(),
  userId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  groups: [] as Array<{ group_id: string }>,
}));
const originalCreateObjectURL = Object.getOwnPropertyDescriptor(
  URL,
  "createObjectURL",
);
const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(
  URL,
  "revokeObjectURL",
);

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    identityGeneration: 1,
    user: {
      id: state.userId,
      courses: [{ course_id: "course-1", role: state.role }],
      groups: state.groups,
    },
  }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/teacher/knowledge",
  useRouter: () => ({ push: state.routerPush }),
}));

import { BrainformWorkspace } from "../components/knowledge/brainform-workspace";
import { LocaleProvider } from "../components/locale";
import { PlatformApiError } from "../lib/api";
import {
  WorkspaceActionsContext,
  type WorkspaceActionRegistry,
  type WorkspaceActions,
} from "../components/workspace-actions";

function ActionsHost({ children }: { children: ReactNode }) {
  const [actions, setActions] = useState<WorkspaceActions>({});
  const registry = useMemo<WorkspaceActionRegistry>(
    () => ({
      register(name, _owner, options) {
        setActions((current) => ({ ...current, [name]: options }));
        return () =>
          setActions((current) => {
            const next = { ...current };
            delete next[name];
            return next;
          });
      },
    }),
    [],
  );
  return (
    <WorkspaceActionsContext.Provider value={registry}>
      {actions.new ? (
        <button
          onClick={actions.new.onClick}
          disabled={actions.new.disabled}
          aria-busy={actions.new.busy || undefined}
        >
          New
        </button>
      ) : null}
      {actions.back ? (
        <button onClick={actions.back.onClick} disabled={actions.back.disabled}>
          Back
        </button>
      ) : null}
      {actions.done ? (
        <button
          type={actions.done.form ? "submit" : "button"}
          form={actions.done.form}
          onClick={actions.done.onClick}
          disabled={actions.done.disabled}
        >
          Done
        </button>
      ) : null}
      {children}
    </WorkspaceActionsContext.Provider>
  );
}

function renderWithActions(
  props: ComponentProps<typeof BrainformWorkspace> = { role: "teacher" },
) {
  return render(
    <LocaleProvider initialLocale="en">
      <ActionsHost>
        <BrainformWorkspace {...props} />
      </ActionsHost>
    </LocaleProvider>,
  );
}

function markdownUpload(name: string, bytes: Promise<ArrayBuffer>) {
  const file = new File([], name, { type: "text/markdown" });
  Object.defineProperty(file, "arrayBuffer", { value: () => bytes });
  return file;
}

function binaryUpload(name: string, bytes: number[], lastModified = 123) {
  return new File([new Uint8Array(bytes)], name, {
    type: "application/pdf",
    lastModified,
  });
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
  visibility: "public",
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
      <ActionsHost>
        <BrainformWorkspace role={role as "teacher" | "student"} />
      </ActionsHost>
    </LocaleProvider>,
  );
}

async function openKnowledgeEditor(name: string) {
  fireEvent.click(
    await screen.findByRole("button", { name: `Edit Knowledge ${name}` }),
  );
  return (await screen.findByRole("textbox", {
    name: "Content",
  })) as HTMLTextAreaElement;
}

beforeEach(() => {
  state.role = "student";
  state.userId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  state.groups = [];
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
    courseAssessmentAttempts: vi.fn().mockResolvedValue([]),
    myAssessmentAttempts: vi.fn().mockResolvedValue([]),
    deleteCourseAssessmentAttempt: vi.fn().mockResolvedValue(undefined),
  };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  if (originalCreateObjectURL) {
    Object.defineProperty(URL, "createObjectURL", originalCreateObjectURL);
  } else {
    Reflect.deleteProperty(URL, "createObjectURL");
  }
  if (originalRevokeObjectURL) {
    Object.defineProperty(URL, "revokeObjectURL", originalRevokeObjectURL);
  } else {
    Reflect.deleteProperty(URL, "revokeObjectURL");
  }
});

describe("Brainform workspace actions", () => {
  // Owner request (2026-10-19): no sidebar New; RAG and Knowledge each add
  // from the Studyform + at their section's top right.
  it("drops the sidebar New and adds from a + on RAG and Knowledge", async () => {
    state.role = "teacher";
    state.api.workspaceDocuments.mockResolvedValue([source]);
    renderWithActions();
    await screen.findAllByText("lesson.md");
    expect(screen.queryByRole("button", { name: "New" })).toBeNull();
    const ragPlus = screen.getByRole("button", { name: "New RAG" });
    const knowledgePlus = screen.getByRole("button", { name: "New Knowledge" });
    // The same + as Studyform's Agents and Teams, in each section heading.
    const rag = screen.getByRole("region", { name: "RAG" });
    const knowledge = screen.getByRole("region", { name: "Knowledge" });
    expect(within(rag).getByRole("button", { name: "New RAG" })).toBe(ragPlus);
    expect(
      within(knowledge).getByRole("button", { name: "New Knowledge" }),
    ).toBe(knowledgePlus);
    expect(ragPlus.className).toContain("addButton");
    expect(knowledgePlus.className).toBe(ragPlus.className);
    expect(ragPlus.parentElement?.className).toContain("sectionHeading");

    fireEvent.click(ragPlus);
    expect(screen.getByLabelText("Upload RAG")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Back" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Done" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "New" })).toBeNull();
  });

  it("hides the Knowledge + from a student and keeps the RAG +", async () => {
    state.role = "student";
    state.groups = [{ group_id: "group-1" }];
    renderWithActions({ role: "student" });
    expect(await screen.findByRole("button", { name: "New RAG" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "New Knowledge" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New" })).toBeNull();
  });

  it("adds neither + to a teacher reading a group's Brainform", async () => {
    state.role = "teacher";
    renderWithActions({ role: "teacher", initialGroupId: "group-1" });
    await screen.findByRole("region", { name: "RAG" });
    expect(screen.queryByRole("button", { name: "New RAG" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New Knowledge" })).toBeNull();
  });

  it("adds a teacher's RAG to the shared course pool, in no Agent", async () => {
    state.role = "teacher";
    state.api.uploadRagLibraryDocument = vi
      .fn()
      .mockResolvedValue({ ...source, id: "document-new" });
    renderWithActions();
    fireEvent.click(await screen.findByRole("button", { name: "New RAG" }));
    const markdown = "# Notes\n\nShared text.";
    fireEvent.change(screen.getByLabelText("Upload RAG"), {
      target: {
        files: [
          markdownUpload(
            "Notes.md",
            Promise.resolve(new TextEncoder().encode(markdown).buffer),
          ),
        ],
      },
    });
    await waitFor(() =>
      expect(
        (screen.getByLabelText("Filename") as HTMLInputElement).value,
      ).toBe("Notes"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(state.api.uploadRagLibraryDocument).toHaveBeenCalledWith(
        { courseId: "course-1" },
        expect.objectContaining({ name: "Notes.md" }),
        expect.objectContaining({ idempotency: expect.any(Object) }),
      ),
    );
    // The list is read again so the new shared RAG shows.
    await waitFor(() =>
      expect(state.api.workspaceDocuments.mock.calls.length).toBeGreaterThan(1),
    );
  });

  it("adds a student's RAG to their group's shared library", async () => {
    state.role = "student";
    state.groups = [{ group_id: "group-1" }];
    state.api.uploadRagLibraryDocument = vi
      .fn()
      .mockResolvedValue({ ...source, id: "document-new" });
    renderWithActions({ role: "student" });
    fireEvent.click(await screen.findByRole("button", { name: "New RAG" }));
    fireEvent.change(screen.getByLabelText("Filename"), {
      target: { value: "Group notes" },
    });
    fireEvent.change(screen.getByLabelText("Content"), {
      target: { value: "# Group notes" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(state.api.uploadRagLibraryDocument).toHaveBeenCalledWith(
        { groupId: "group-1" },
        expect.objectContaining({ name: "Group notes.md" }),
        expect.anything(),
      ),
    );
  });

  it("deletes a Knowledge with its current revisions after confirming", async () => {
    state.role = "teacher";
    state.api.brainformKnowledge.mockResolvedValue([
      {
        canonical_set_id: "set-1",
        source_agent_display_name: "Socrates",
        knowledge_display_name: "Socrates Knowledge",
        version_seq: 1,
        content_hash: "b".repeat(64),
        projection_available: true,
        can_read: true,
        can_edit: true,
        created_at: "2026-10-06T00:00:00Z",
      },
    ]);
    state.api.knowledgeSet.mockResolvedValue({
      id: "set-1",
      metadata_revision: 3,
      content_revision: 5,
    });
    state.api.deleteKnowledgeSet = vi.fn().mockResolvedValue({});
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWorkspace("teacher");

    fireEvent.click(
      await screen.findByRole("button", { name: "Delete Socrates Knowledge" }),
    );
    await waitFor(() =>
      expect(state.api.deleteKnowledgeSet).toHaveBeenCalledWith(
        "set-1",
        { expected_metadata_revision: 3, expected_content_revision: 5 },
        expect.anything(),
      ),
    );
  });

  // Owner request (2026-10-13): the Knowledge + (the sidebar New until
  // 2026-10-19) opens a new Knowledge; a
  // picked Markdown file fills it and Done saves it, named after the file.
  it("adds Knowledge from a Markdown file through + and Done", async () => {
    state.role = "teacher";
    state.api.createKnowledgeSet = vi
      .fn()
      .mockResolvedValue({ id: "set-new", display_name: "Form A" });
    let finishSave: (value: object) => void = () => {};
    state.api.saveKnowledgeMarkdown = vi.fn(
      () => new Promise((resolve) => (finishSave = resolve)),
    );
    renderWorkspace("teacher");

    fireEvent.click(
      await screen.findByRole("button", { name: "New Knowledge" }),
    );
    expect(
      (screen.getByRole("button", { name: "Done" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    const markdown = "# Form A\n\n## Questions\n";
    fireEvent.change(
      screen.getByLabelText("Upload a Markdown file as Knowledge"),
      {
        target: {
          files: [
            markdownUpload(
              "Form A.md",
              Promise.resolve(new TextEncoder().encode(markdown).buffer),
            ),
          ],
        },
      },
    );
    await waitFor(() =>
      expect(
        (screen.getByLabelText("Filename") as HTMLInputElement).value,
      ).toBe("Form A"),
    );
    expect(
      (screen.getByLabelText("Content") as HTMLTextAreaElement).value,
    ).toBe(markdown);
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(state.api.saveKnowledgeMarkdown).toHaveBeenCalledWith(
        "set-new",
        { expected_version_seq: 0, markdown },
        expect.anything(),
      ),
    );
    expect(state.api.createKnowledgeSet).toHaveBeenCalledWith(
      "course-1",
      { display_name: "Form A" },
      expect.anything(),
    );
    // Done returns to the list; the + shows the work and no notice follows.
    const busyNew = screen.getByRole("button", { name: "New Knowledge" });
    expect(busyNew.getAttribute("aria-busy")).toBe("true");
    finishSave({});
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "New Knowledge" })
          .getAttribute("aria-busy"),
      ).toBeNull(),
    );
    expect(screen.queryByRole("status")).toBeNull();
    // The section itself has no upload button any more.
    expect(
      screen.queryByLabelText("Upload a Markdown file as Knowledge"),
    ).toBeNull();
  });

  it("leaves a new Knowledge unsaved on Back", async () => {
    state.role = "teacher";
    state.api.createKnowledgeSet = vi.fn();
    renderWorkspace("teacher");
    fireEvent.click(
      await screen.findByRole("button", { name: "New Knowledge" }),
    );
    fireEvent.change(screen.getByLabelText("Filename"), {
      target: { value: "Draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(
      await screen.findByRole("button", { name: "New Knowledge" }),
    ).toBeTruthy();
    expect(state.api.createKnowledgeSet).not.toHaveBeenCalled();
  });

  it("keeps a private Agent's RAG out of Brainform", async () => {
    state.role = "teacher";
    state.api.workspaceDocuments.mockResolvedValue([
      source,
      {
        ...source,
        id: "document-private",
        visibility: "private",
        source_filename: "test2.md",
      },
    ]);
    renderWorkspace("teacher");
    await screen.findAllByText("lesson.md");
    expect(screen.queryByText("test2.md")).toBeNull();
  });

  it("replaces an existing RAG source with an imported DOCX through the server CAS API", async () => {
    state.role = "teacher";
    state.api.workspaceDocuments.mockResolvedValue([source]);
    state.api.replaceKnowledgeDocument.mockResolvedValue({
      ...source,
      source_filename: "lesson.docx",
      content_hash: "c".repeat(64),
      index_revision: 5,
    });
    renderWorkspace("teacher");
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Edit lesson.md" }))[0],
    );
    const docx = new File(
      [new Uint8Array([80, 75, 3, 4, 0, 255])],
      "lesson.docx",
      {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      },
    );
    fireEvent.change(await screen.findByLabelText("Import a file"), {
      target: { files: [docx] },
    });
    expect(
      await screen.findByText(
        "lesson.docx is selected. It will be imported when you save.",
      ),
    ).toBeTruthy();
    expect(state.api.replaceKnowledgeDocument).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(state.api.replaceKnowledgeDocument).toHaveBeenCalledTimes(1),
    );
    expect(state.api.replaceKnowledgeDocument).toHaveBeenCalledWith(
      "document-1",
      expect.objectContaining({ name: "lesson.docx" }),
      "a".repeat(64),
      4,
      expect.objectContaining({ idempotency: expect.any(Object) }),
    );
  });

  // Owner request (2026-10-13): saving a RAG file updates every Agent that
  // reads it; the server then moves their Teams to the new version.
  it("publishes a new version of the Agent that reads a saved RAG file", async () => {
    state.role = "teacher";
    state.api.workspaceDocuments.mockResolvedValue([source]);
    state.api.replaceKnowledgeDocument.mockResolvedValue({
      ...source,
      source_filename: "lesson.docx",
      content_hash: "c".repeat(64),
      index_revision: 5,
    });
    state.api.version = vi.fn().mockResolvedValue({
      id: "agent-version-1",
      revision: 3,
      state: "published",
      agent_md: "# Socrates",
      enabled_documents: [source],
    });
    state.api.agent = vi.fn().mockResolvedValue({
      id: "agent-1",
      can_edit: true,
      current_draft_version_id: null,
    });
    state.api.nextVersion = vi
      .fn()
      .mockResolvedValue({ id: "agent-version-2", revision: 0 });
    state.api.publish = vi.fn().mockResolvedValue({ id: "agent-version-2" });
    renderWorkspace("teacher");
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Edit lesson.md" }))[0],
    );
    fireEvent.change(await screen.findByLabelText("Import a file"), {
      target: {
        files: [binaryUpload("lesson.docx", [80, 75, 3, 4, 0, 255])],
      },
    });
    await screen.findByText(
      "lesson.docx is selected. It will be imported when you save.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() =>
      expect(state.api.publish).toHaveBeenCalledWith("agent-version-2", 0),
    );
    expect(state.api.nextVersion).toHaveBeenCalledWith("agent-1");
    // Save returns to the three-column list; other Done surfaces show no success tip.
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Content" })).toBeNull(),
    );
    expect(screen.queryByText(/Markdown source saved/i)).toBeNull();
    expect(screen.getByRole("button", { name: "Edit lesson.md" })).toBeTruthy();
  });

  it("enters a RAG file by clicking its title, which is an Agent-style title button", async () => {
    state.role = "teacher";
    state.api.workspaceDocuments.mockResolvedValue([source]);
    renderWorkspace("teacher");
    const title = (
      await screen.findAllByRole("button", { name: "Edit lesson.md" })
    )[0];
    // The title itself is the button, with the same classes as an Agent
    // tile's title; there is no separate enter button.
    expect(title.textContent).toBe("lesson.md");
    expect(title.classList.contains("agent-tile-name")).toBe(true);
    expect(title.classList.contains("text-link")).toBe(true);
    const row = title.closest("li")!;
    expect(row.querySelector("[class*='enterButton']")).toBeNull();

    // Clicking the row outside the title does not enter.
    fireEvent.click(row);
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(screen.queryByRole("textbox", { name: "Content" })).toBeNull();

    fireEvent.click(title);
    expect(
      await screen.findByRole("textbox", { name: "Content" }),
    ).toBeTruthy();
  });

  it("enters Knowledge through its title button and does not enter while generating", async () => {
    state.role = "teacher";
    state.api.brainformKnowledge.mockResolvedValue([
      {
        canonical_set_id: "set-ready",
        knowledge_display_name: "Ready Knowledge",
        version_seq: 2,
        can_edit: true,
        content_hash: "a".repeat(64),
        generation_state: "completed",
        safe_error_code: null,
      },
      {
        canonical_set_id: "set-running",
        knowledge_display_name: "Running Knowledge",
        version_seq: 1,
        can_edit: true,
        content_hash: "b".repeat(64),
        generation_state: "running",
        safe_error_code: null,
      },
    ]);
    renderWorkspace("teacher");
    const ready = await screen.findByRole("button", {
      name: "Edit Knowledge Ready Knowledge",
    });
    expect(ready.textContent).toBe("Ready Knowledge");
    expect(ready.classList.contains("text-link")).toBe(true);
    expect(ready.getAttribute("aria-disabled")).toBeNull();
    const running = screen.getByRole("button", {
      name: "Edit Knowledge Running Knowledge",
    });
    expect(running.getAttribute("aria-disabled")).toBe("true");
  });

  it("renames a RAG file in place on a double-click, keeping its extension", async () => {
    state.role = "teacher";
    state.api.workspaceDocuments.mockResolvedValue([source]);
    renderWorkspace("teacher");
    await screen.findAllByRole("button", { name: "Edit lesson.md" });
    fireEvent.doubleClick(screen.getByText("lesson.md"));
    const name = await screen.findByRole("textbox", { name: "RAG file name" });
    expect((name as HTMLInputElement).value).toBe("lesson");
    fireEvent.change(name, { target: { value: "renamed" } });
    fireEvent.blur(name);
    await waitFor(() =>
      expect(state.api.renameKnowledgeDocument).toHaveBeenCalledWith(
        "document-1",
        { expected_filename: "lesson.md", filename: "renamed.md" },
        expect.anything(),
      ),
    );
    // The double-click renamed; it did not also open the editor.
    expect(state.api.downloadKnowledge).not.toHaveBeenCalled();
  });

  it("opens the Knowledge editor from its name, as a RAG name does", async () => {
    state.role = "teacher";
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
      },
    ]);
    state.api.knowledgeMarkdown.mockResolvedValue({
      audience: "full",
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      version_seq: 1,
      content_hash: "b".repeat(64),
      markdown: "# Canonical body",
      projection_available: true,
      can_read: true,
      can_edit: true,
      created_at: "2026-10-04T00:00:00Z",
    });
    renderWorkspace("teacher");

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Edit Knowledge Socrates Knowledge",
      }),
    );
    expect(
      ((await screen.findByLabelText("Content")) as HTMLTextAreaElement).value,
    ).toBe("# Canonical body");
    expect(screen.getByRole("button", { name: "Done" })).toBeTruthy();
  });

  it("keeps an RAG draft after a replacement CAS conflict and refreshes its source row", async () => {
    state.role = "teacher";
    state.userId = "22222222-2222-4222-8222-222222222222";
    state.api.workspaceDocuments.mockResolvedValue([source]);
    state.api.replaceKnowledgeDocument.mockRejectedValue(
      new PlatformApiError(409, "stale source", { code: "stale_revision" }),
    );
    renderWorkspace("teacher");
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Edit lesson.md" }))[0],
    );
    const content = await screen.findByRole("textbox", {
      name: "Content",
    });
    fireEvent.change(content, { target: { value: "# My pending edit" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() =>
      expect(state.api.replaceKnowledgeDocument).toHaveBeenCalledTimes(1),
    );
    expect(await screen.findByText(/Your draft is kept/i)).toBeTruthy();
    expect(content).toHaveProperty("value", "# My pending edit");
    expect(state.api.workspaceDocuments.mock.calls.length).toBeGreaterThan(1);
  });

  it("keeps readable RAG view and download while omitting write actions for a read-only row", async () => {
    state.role = "teacher";
    state.userId = "33333333-3333-4333-8333-333333333333";
    state.api.workspaceDocuments.mockResolvedValue([
      { ...source, can_manage_visibility: false },
    ]);
    const createObjectURL = vi.fn(() => "blob:knowledge");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      () => undefined,
    );
    renderWorkspace("teacher");

    const viewButtons = await screen.findAllByRole("button", {
      name: "View lesson.md",
    });
    expect(viewButtons).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Edit lesson.md" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Hide lesson.md" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Reindex lesson.md" }),
    ).toBeNull();
    fireEvent.click(viewButtons[0]);
    expect(await screen.findByText("Source")).toBeTruthy();
    expect(state.api.downloadKnowledge).toHaveBeenCalledWith("document-1");

    await screen.findByRole("button", { name: "Back" });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Download lesson.md" }));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:knowledge");
  });

  it("reuses the same idempotency key for an uncertain reindex and hide retry", async () => {
    state.role = "teacher";
    state.userId = "44444444-4444-4444-8444-444444444444";
    const failedSource = { ...source, index_status: "failed" };
    state.api.workspaceDocuments.mockResolvedValue([failedSource]);
    const reindexKeys: string[] = [];
    state.api.reindex = vi.fn(
      async (
        _documentId: string,
        options: { idempotency: { key: string } },
      ) => {
        reindexKeys.push(options.idempotency.key);
        if (reindexKeys.length === 1) throw new TypeError("connection reset");
        return {};
      },
    );
    const hideKeys: string[] = [];
    state.api.hideKnowledge = vi.fn(
      async (
        _documentId: string,
        options: { idempotency: { key: string } },
      ) => {
        hideKeys.push(options.idempotency.key);
        if (hideKeys.length === 1) throw new TypeError("connection reset");
        return {};
      },
    );
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWorkspace("teacher");

    fireEvent.click(
      await screen.findByRole("button", { name: "Reindex lesson.md" }),
    );
    await waitFor(() => expect(state.api.reindex).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(state.api.reindex).toHaveBeenCalledTimes(2));
    expect(reindexKeys[1]).toBe(reindexKeys[0]);

    fireEvent.click(
      await screen.findByRole("button", { name: "Hide lesson.md" }),
    );
    await waitFor(() =>
      expect(state.api.hideKnowledge).toHaveBeenCalledTimes(1),
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(state.api.hideKnowledge).toHaveBeenCalledTimes(2),
    );
    expect(hideKeys[1]).toBe(hideKeys[0]);
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("does not repeat a settled reindex when the authoritative list refresh fails", async () => {
    state.role = "teacher";
    state.userId = "77777777-7777-4777-8777-777777777777";
    const failedSource = { ...source, index_status: "failed" };
    let accepted = false;
    let readsAfterMutation = 0;
    state.api.workspaceDocuments = vi.fn(async () => {
      if (!accepted) return [failedSource];
      readsAfterMutation += 1;
      if (readsAfterMutation === 1) throw new TypeError("refresh unavailable");
      return [failedSource];
    });
    state.api.reindex = vi.fn(async () => {
      accepted = true;
      return {};
    });
    renderWorkspace("teacher");

    fireEvent.click(
      await screen.findByRole("button", { name: "Reindex lesson.md" }),
    );
    await waitFor(() => expect(state.api.reindex).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText(
        "Maya could not be reached. Check your connection and try again.",
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(readsAfterMutation).toBeGreaterThan(1));
    expect(state.api.reindex).toHaveBeenCalledTimes(1);
  });

  it("does not replay a completed reindex when refreshing the RAG list fails", async () => {
    state.role = "teacher";
    state.userId = "55555555-5555-4555-8555-555555555555";
    const failedSource = { ...source, index_status: "failed" };
    let reindexAccepted = false;
    let postMutationReads = 0;
    state.api.workspaceDocuments = vi.fn(async () => {
      if (!reindexAccepted) return [failedSource];
      postMutationReads += 1;
      if (postMutationReads === 1) throw new TypeError("refresh unavailable");
      return [failedSource];
    });
    state.api.reindex = vi.fn(async () => {
      reindexAccepted = true;
      return {};
    });
    renderWorkspace("teacher");

    fireEvent.click(
      await screen.findByRole("button", { name: "Reindex lesson.md" }),
    );
    await waitFor(() => expect(state.api.reindex).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText(
        "Maya could not be reached. Check your connection and try again.",
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(state.api.workspaceDocuments.mock.calls.length).toBeGreaterThan(1),
    );
    expect(state.api.reindex).toHaveBeenCalledTimes(1);
  });

  it("keeps an existing draft when an imported file has invalid UTF-8 or is not Markdown", async () => {
    state.role = "teacher";
    // Drafts are remembered per account; start from an untouched one.
    state.userId = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
    state.api.workspaceDocuments.mockResolvedValue([source]);
    renderWithActions();
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Edit lesson.md" }))[0],
    );
    const content = await screen.findByRole("textbox", {
      name: "Content",
    });
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
    expect(screen.getByDisplayValue("lesson.md")).toBeTruthy();
    const unsupported = markdownUpload(
      "wrong.txt",
      Promise.resolve(new ArrayBuffer(0)),
    );
    fireEvent.change(screen.getByLabelText("Import a file"), {
      target: { files: [unsupported] },
    });
    expect(screen.getByDisplayValue("# Keep my draft")).toBeTruthy();
    expect(state.api.replaceKnowledgeDocument).not.toHaveBeenCalled();
  });

  it("does not let a file read from the previous identity overwrite a new actor draft", async () => {
    state.role = "teacher";
    state.userId = "ffffffff-ffff-4fff-8fff-ffffffffffff";
    state.api.workspaceDocuments.mockResolvedValue([source]);
    const view = renderWithActions();
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Edit lesson.md" }))[0],
    );
    await screen.findByRole("textbox", { name: "Content" });
    let finish!: (bytes: ArrayBuffer) => void;
    const bytes = new Promise<ArrayBuffer>((resolve) => {
      finish = resolve;
    });
    fireEvent.change(screen.getByLabelText("Import a file"), {
      target: { files: [markdownUpload("late.md", bytes)] },
    });
    state.userId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
    view.rerender(
      <LocaleProvider initialLocale="en">
        <ActionsHost>
          <BrainformWorkspace role="teacher" />
        </ActionsHost>
      </LocaleProvider>,
    );
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Edit lesson.md" }))[0],
    );
    fireEvent.change(await screen.findByRole("textbox", { name: "Content" }), {
      target: { value: "# New draft" },
    });
    finish(new TextEncoder().encode("# Old file").buffer);
    await bytes;
    await waitFor(() =>
      expect(screen.getByDisplayValue("# New draft")).toBeTruthy(),
    );
    expect(screen.getByDisplayValue("lesson.md")).toBeTruthy();
    expect(screen.queryByDisplayValue("late.md")).toBeNull();
    expect(state.api.replaceKnowledgeDocument).not.toHaveBeenCalled();
  });

  it("shows teachers Record by assessment Team, then every student's result", async () => {
    state.role = "teacher";
    const attempt = {
      user_id: "student-1",
      student_name: "Ada",
      test_name: "Keynotes · Formal diagnostic questions · V1.0",
      team_name: "Keynotes",
      status: "completed",
      phase: "completed",
      conversation_id: "4afc794f-1111-4111-8111-111111111111",
      group_name: "Group A",
      started_at: "2026-10-13T08:00:00Z",
      ended_at: "2026-10-13T08:20:00Z",
      points_awarded: 3,
      points_total: 4,
      questions: [
        {
          number: 1,
          prompt: "What is ren?",
          answers: ["Humaneness"],
          skipped: false,
          points_awarded: 1,
          points_total: 1,
          feedback: "Right.",
        },
      ],
      report_download_path: "/api/v1/learning/reports/r/download?revision_id=v",
    };
    state.api.courseAssessmentAttempts.mockResolvedValue([
      { ...attempt, attempt_id: "attempt-1" },
      {
        ...attempt,
        attempt_id: "attempt-2",
        user_id: "student-2",
        student_name: "Ben",
        status: "in_progress",
        phase: "answering",
        points_awarded: null,
        points_total: null,
        questions: [],
        report_download_path: null,
      },
    ]);
    renderWithActions();

    expect(await screen.findByRole("heading", { name: "Record" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Memory" })).toBeNull();
    expect(state.api.courseAssessmentAttempts).toHaveBeenCalledWith("course-1");
    const team = await screen.findByRole("button", {
      name: "Open the results for Keynotes",
    });
    expect(team.textContent).toContain("Students 2 · Attempts 2");
    fireEvent.click(team);

    expect(
      await screen.findByRole("heading", { name: "Keynotes" }),
    ).toBeTruthy();
    const ada = screen.getByRole("button", { name: /^Ada.*3 \/ 4$/ });
    expect(ada.textContent).toContain(
      "Group A · Formal diagnostic questions · V1.0",
    );
    expect(
      screen.getByRole("button", { name: /^Ben.*Unfinished$/ }),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", {
          name: "Download the report for Keynotes · Formal diagnostic questions · V1.0",
        })
        .getAttribute("href"),
    ).toBe("/api/v1/learning/reports/r/download?revision_id=v");
    fireEvent.click(ada);
    expect(screen.getByRole("cell", { name: "Humaneness" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "Right." })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(
      await screen.findByRole("button", {
        name: "Open the results for Keynotes",
      }),
    ).toBeTruthy();
  });

  // Owner request (2026-10-18): Record keeps revoked versions' and
  // unfinished attempts, and a teacher can delete (hide) one after a confirm.
  it("labels revoked and unfinished attempts and deletes one after a confirm", async () => {
    state.role = "teacher";
    const revoked = {
      attempt_id: "attempt-revoked",
      user_id: "student-1",
      student_name: "Ada",
      test_name: "Keynotes · Formal diagnostic questions · V1.0",
      team_name: "Keynotes",
      status: "in_progress",
      phase: "answering",
      conversation_id: "4afc794f-5555-4555-8555-555555555555",
      group_name: "Group A",
      started_at: "2026-10-16T02:25:00Z",
      ended_at: null,
      points_awarded: null,
      points_total: null,
      questions: [
        {
          number: 1,
          prompt: "What is ren?",
          answers: ["Half an answer"],
          skipped: false,
          points_awarded: null,
          points_total: null,
          feedback: "",
        },
      ],
      report_download_path: null,
      publication_state: "revoked",
      version_label: "V1.0",
    };
    state.api.courseAssessmentAttempts
      .mockResolvedValueOnce([revoked])
      .mockResolvedValue([]);
    const confirm = vi.spyOn(window, "confirm");
    renderWithActions();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open the results for Keynotes",
      }),
    );
    const row = await screen.findByRole("button", {
      name: /^Ada.*Unfinished$/,
    });
    expect(row.textContent).toContain(
      "Formal diagnostic questions · V1.0 · Revoked version",
    );
    fireEvent.click(row);
    expect(screen.getByRole("cell", { name: "Half an answer" })).toBeTruthy();

    const remove = screen.getByRole("button", {
      name: "Delete Ada's attempt",
    });
    confirm.mockReturnValueOnce(false);
    fireEvent.click(remove);
    expect(state.api.deleteCourseAssessmentAttempt).not.toHaveBeenCalled();

    confirm.mockReturnValueOnce(true);
    fireEvent.click(remove);
    await waitFor(() =>
      expect(state.api.deleteCourseAssessmentAttempt).toHaveBeenCalledWith(
        "course-1",
        "attempt-revoked",
      ),
    );
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /^Ada/ })).toBeNull(),
    );
    confirm.mockRestore();
  });

  it("never offers a student the Record delete", async () => {
    state.api.myAssessmentAttempts.mockResolvedValue([
      {
        attempt_id: "own-attempt-2",
        user_id: state.userId,
        student_name: "Bowen",
        test_name: "Keynotes · Formal diagnostic questions · V1.0",
        team_name: "Keynotes",
        status: "completed",
        phase: "completed",
        conversation_id: "4afc794f-4444-4444-8444-444444444444",
        group_name: "Group A",
        started_at: "2026-10-16T02:25:00Z",
        ended_at: "2026-10-16T02:45:00Z",
        points_awarded: null,
        points_total: null,
        questions: [],
        report_download_path: null,
      },
    ]);
    renderWorkspace("student");
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open your answers for Keynotes",
      }),
    );
    await screen.findByRole("heading", { name: "Keynotes" });
    expect(
      screen.queryByRole("button", { name: /^Delete .*'s attempt$/ }),
    ).toBeNull();
    expect(state.api.deleteCourseAssessmentAttempt).not.toHaveBeenCalled();
  });

  it("shows the last Record at once while it refreshes (#123)", async () => {
    state.role = "teacher";
    state.api.courseAssessmentAttempts.mockResolvedValue([
      {
        attempt_id: "attempt-cached",
        user_id: "student-1",
        student_name: "Ada",
        test_name: "Cached · Formal diagnostic questions · V1.0",
        team_name: "Cached",
        status: "completed",
        phase: "completed",
        conversation_id: "4afc794f-2222-4222-8222-222222222222",
        group_name: "Group A",
        started_at: "2026-10-13T08:00:00Z",
        ended_at: "2026-10-13T08:20:00Z",
        points_awarded: 1,
        points_total: 1,
        questions: [],
        report_download_path: null,
      },
    ]);
    const first = renderWithActions();
    await screen.findByRole("button", { name: "Open the results for Cached" });
    first.unmount();

    // The refresh never answers: the cached list is what shows.
    state.api.courseAssessmentAttempts.mockReturnValue(new Promise(() => {}));
    renderWithActions();
    expect(
      await screen.findByRole("button", {
        name: "Open the results for Cached",
      }),
    ).toBeTruthy();
    expect(state.api.courseAssessmentAttempts).toHaveBeenCalledTimes(2);
  });

  // Owner request (2026-10-18): a student's Memory became Record, listing
  // only the student's own answers per assessment Team.
  it("shows a student's own Record and never reads course results", async () => {
    state.api.myAssessmentAttempts.mockResolvedValue([
      {
        attempt_id: "own-attempt-1",
        user_id: state.userId,
        student_name: "Bowen",
        test_name: "Keynotes · Formal diagnostic questions · V1.0",
        team_name: "Keynotes",
        status: "in_progress",
        phase: "answering",
        conversation_id: "4afc794f-3333-4333-8333-333333333333",
        group_name: "Group A",
        started_at: "2026-10-16T02:25:00Z",
        ended_at: null,
        points_awarded: null,
        points_total: null,
        questions: [
          {
            number: 1,
            prompt: "What is ren?",
            answers: ["Humaneness"],
            skipped: false,
            points_awarded: null,
            points_total: null,
            feedback: "",
          },
          {
            number: 2,
            prompt: "What is li?",
            answers: [],
            skipped: false,
            points_awarded: null,
            points_total: null,
            feedback: "",
          },
        ],
        report_download_path: null,
      },
    ]);
    renderWorkspace("student");

    expect(await screen.findByRole("heading", { name: "Record" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Memory" })).toBeNull();
    expect(state.api.myAssessmentAttempts).toHaveBeenCalledWith("course-1");
    expect(state.api.courseAssessmentAttempts).not.toHaveBeenCalled();
    const team = await screen.findByRole("button", {
      name: "Open your answers for Keynotes",
    });
    expect(team.textContent).toContain("Attempts 1");
    expect(team.textContent).not.toContain("Students");
    fireEvent.click(team);

    expect(
      await screen.findByRole("heading", { name: "Keynotes" }),
    ).toBeTruthy();
    const attempt = screen.getByRole("button", {
      name: /^Formal diagnostic questions · V1\.0.*In progress$/,
    });
    expect(screen.queryByText("Average score")).toBeNull();
    fireEvent.click(attempt);
    expect(screen.getByRole("cell", { name: "Humaneness" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "(not answered)" })).toBeTruthy();
    // Scores and feedback stay with the teacher.
    expect(screen.queryByRole("columnheader", { name: "Points" })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Feedback" })).toBeNull();
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
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

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

  it("groups canonical Knowledge once and opens the shared asset without listing Agents", async () => {
    state.role = "teacher";
    state.api.brainformKnowledge.mockResolvedValue([
      {
        agent_id: "agent-1",
        canonical_set_id: "set-1",
        source_agent_display_name: "Socrates",
        knowledge_display_name: "Shared notes",
        can_read: true,
        can_edit: true,
        version_seq: 1,
        content_hash: "b".repeat(64),
        generation_state: "completed",
        safe_error_code: null,
      },
      {
        agent_id: "agent-2",
        canonical_set_id: "set-1",
        source_agent_display_name: "Mencius",
        knowledge_display_name: "Shared notes",
        can_read: true,
        can_edit: true,
        version_seq: 1,
        content_hash: "b".repeat(64),
        generation_state: "completed",
        safe_error_code: null,
      },
    ]);
    renderWorkspace("teacher");

    // Owner decision (2026-10-13): rows show no "Used by" line; the name opens
    // the editor and a double-click renames. Detail no longer lists Agents.
    await screen.findByRole("button", { name: "Edit Knowledge Shared notes" });
    expect(screen.queryByText(/Used by/)).toBeNull();
    expect(
      screen.getAllByRole("button", { name: "Edit Knowledge Shared notes" }),
    ).toHaveLength(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Edit Knowledge Shared notes" }),
    );

    expect(
      await screen.findByRole("textbox", { name: "Filename" }),
    ).toBeTruthy();
    expect(
      await screen.findByRole("textbox", { name: "Content" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("region", { name: "Agents using this Knowledge" }),
    ).toBeNull();
    expect(state.api.knowledgeMarkdown).toHaveBeenCalledWith("set-1");
  });

  it("shows a running Knowledge by name with a busy spinner until it completes", async () => {
    state.role = "teacher";
    const running = {
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Question bank",
      can_read: true,
      can_edit: true,
      version_seq: null,
      content_hash: null,
      generation_state: "running",
      safe_error_code: null,
    };
    state.api.brainformKnowledge
      .mockResolvedValueOnce([running])
      .mockResolvedValue([
        {
          ...running,
          version_seq: 1,
          content_hash: "b".repeat(64),
          generation_state: "completed",
        },
      ]);
    renderWorkspace("teacher");

    const busy = await screen.findByRole("button", {
      name: "Generating Question bank",
    });
    expect((busy as HTMLButtonElement).disabled).toBe(true);
    expect(busy.getAttribute("aria-busy")).toBe("true");
    expect(
      screen.queryByRole("button", { name: "Download Question bank" }),
    ).toBeNull();

    expect(
      await screen.findByRole("button", { name: "Download Question bank" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Generating Question bank" }),
    ).toBeNull();
  });

  it("opens an empty first Knowledge draft after a 404 and saves with expected sequence zero", async () => {
    state.role = "teacher";
    state.userId = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
    state.api.brainformKnowledge.mockResolvedValue([
      {
        agent_id: "agent-1",
        canonical_set_id: "set-1",
        source_agent_display_name: "Socrates",
        knowledge_display_name: "Empty Knowledge",
        can_read: true,
        can_edit: true,
        version_seq: 0,
        content_hash: null,
        generation_state: "failed",
        safe_error_code: "provider_confirmation_required",
      },
    ]);
    state.api.knowledgeMarkdown.mockRejectedValueOnce(
      new PlatformApiError(404, "no current Knowledge version"),
    );
    state.api.saveKnowledgeMarkdown.mockResolvedValue({
      audience: "full",
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Empty Knowledge",
      version_seq: 1,
      content_hash: "c".repeat(64),
      markdown: "# Teacher draft",
      projection_available: true,
      can_read: true,
      can_edit: true,
      created_at: "2026-10-05T00:00:00Z",
    });
    renderWorkspace("teacher");
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Edit Knowledge Empty Knowledge",
      }),
    );
    expect(
      await screen.findByText(
        "No Knowledge version is published yet. This is an empty Markdown draft.",
      ),
    ).toBeTruthy();
    const editor = await screen.findByRole("textbox", { name: "Content" });
    expect((editor as HTMLTextAreaElement).value).toBe("");
    fireEvent.change(editor, { target: { value: "# Teacher draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() =>
      expect(state.api.saveKnowledgeMarkdown).toHaveBeenCalledWith(
        "set-1",
        { expected_version_seq: 0, markdown: "# Teacher draft" },
        expect.objectContaining({ idempotency: expect.any(Object) }),
      ),
    );
  });

  it("keeps an uncertain canonical Markdown key for unchanged text and rotates it after edits", async () => {
    state.role = "teacher";
    state.userId = "abababab-abab-4bab-8bab-abababababab";
    const row = {
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      can_read: true,
      can_edit: true,
      version_seq: 4,
      content_hash: "b".repeat(64),
      generation_state: "completed",
      safe_error_code: null,
    };
    const markdown = {
      audience: "full",
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      version_seq: 4,
      content_hash: "b".repeat(64),
      markdown: "# Original",
      projection_available: true,
      can_read: true,
      can_edit: true,
      created_at: "2026-10-06T00:00:00Z",
    };
    state.api.brainformKnowledge.mockResolvedValue([row]);
    state.api.knowledgeMarkdown.mockResolvedValue(markdown);
    const keys: string[] = [];
    state.api.saveKnowledgeMarkdown = vi.fn(
      async (
        _setId: string,
        _body: { expected_version_seq: number; markdown: string },
        options: { idempotency: { key: string } },
      ) => {
        keys.push(options.idempotency.key);
        if (keys.length < 3) throw new TypeError("connection reset");
        return {
          ...markdown,
          version_seq: 5,
          markdown: "# Changed again",
        };
      },
    );
    renderWorkspace("teacher");

    const editor = await openKnowledgeEditor("Socrates Knowledge");
    fireEvent.change(editor, { target: { value: "# Changed" } });
    const done = () => screen.getByRole("button", { name: "Done" });
    fireEvent.click(done());
    await waitFor(() =>
      expect(state.api.saveKnowledgeMarkdown).toHaveBeenCalledTimes(1),
    );
    await waitFor(() =>
      expect((done() as HTMLButtonElement).disabled).toBe(false),
    );

    fireEvent.change(editor, { target: { value: "# Changed" } });
    fireEvent.click(done());
    await waitFor(() =>
      expect(state.api.saveKnowledgeMarkdown).toHaveBeenCalledTimes(2),
    );
    expect(keys[1]).toBe(keys[0]);
    await waitFor(() =>
      expect((done() as HTMLButtonElement).disabled).toBe(false),
    );

    fireEvent.change(editor, { target: { value: "# Changed again" } });
    fireEvent.click(done());
    await waitFor(() =>
      expect(state.api.saveKnowledgeMarkdown).toHaveBeenCalledTimes(3),
    );
    expect(keys[2]).not.toBe(keys[1]);
    expect(state.api.saveKnowledgeMarkdown).toHaveBeenLastCalledWith(
      "set-1",
      { expected_version_seq: 4, markdown: "# Changed again" },
      expect.objectContaining({ idempotency: expect.any(Object) }),
    );
  });

  it("keeps the canonical editor read-only while its publish is pending, then returns to the list", async () => {
    state.role = "teacher";
    state.userId = "cdcdcdcd-cdcd-4dcd-8dcd-cdcdcdcdcdcd";
    const row = {
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      can_read: true,
      can_edit: true,
      version_seq: 4,
      content_hash: "b".repeat(64),
      generation_state: "completed",
      safe_error_code: null,
    };
    const markdown = {
      audience: "full",
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      version_seq: 4,
      content_hash: "b".repeat(64),
      markdown: "# Original",
      projection_available: true,
      can_read: true,
      can_edit: true,
      created_at: "2026-10-06T00:00:00Z",
    };
    state.api.brainformKnowledge.mockResolvedValue([row]);
    state.api.knowledgeMarkdown.mockResolvedValue(markdown);
    let finishSave!: (next: typeof markdown) => void;
    state.api.saveKnowledgeMarkdown.mockImplementationOnce(
      () => new Promise((resolve) => (finishSave = resolve)),
    );
    renderWorkspace("teacher");

    const editor = await openKnowledgeEditor("Socrates Knowledge");
    fireEvent.change(editor, { target: { value: "# Sent body" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(state.api.saveKnowledgeMarkdown).toHaveBeenCalledTimes(1),
    );

    expect(editor.readOnly).toBe(true);
    expect(editor.value).toBe("# Sent body");
    await act(async () =>
      finishSave({ ...markdown, version_seq: 5, markdown: "# Sent body" }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Content" })).toBeNull(),
    );
    expect(
      screen.queryByText("Knowledge published as a new version."),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "Edit Knowledge Socrates Knowledge" }),
    ).toBeTruthy();
  });

  it("unlocks the canonical editor after an uncertain save and preserves its draft for retry", async () => {
    state.role = "teacher";
    state.userId = "dededede-dede-4ded-8ded-dededededede";
    const row = {
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      can_read: true,
      can_edit: true,
      version_seq: 4,
      content_hash: "b".repeat(64),
      generation_state: "completed",
      safe_error_code: null,
    };
    const markdown = {
      audience: "full",
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      version_seq: 4,
      content_hash: "b".repeat(64),
      markdown: "# Original",
      projection_available: true,
      can_read: true,
      can_edit: true,
      created_at: "2026-10-06T00:00:00Z",
    };
    state.api.brainformKnowledge.mockResolvedValue([row]);
    state.api.knowledgeMarkdown.mockResolvedValue(markdown);
    const keys: string[] = [];
    state.api.saveKnowledgeMarkdown = vi.fn(
      async (
        _setId: string,
        _body: { expected_version_seq: number; markdown: string },
        options: { idempotency: { key: string } },
      ) => {
        keys.push(options.idempotency.key);
        if (keys.length === 1) throw new TypeError("connection reset");
        return { ...markdown, version_seq: 5, markdown: "# Kept draft" };
      },
    );
    renderWorkspace("teacher");

    const editor = await openKnowledgeEditor("Socrates Knowledge");
    fireEvent.change(editor, { target: { value: "# Kept draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(state.api.saveKnowledgeMarkdown).toHaveBeenCalledTimes(1),
    );
    await waitFor(() => expect(editor.readOnly).toBe(false));
    expect(editor.value).toBe("# Kept draft");

    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(state.api.saveKnowledgeMarkdown).toHaveBeenCalledTimes(2),
    );
    expect(keys[1]).toBe(keys[0]);
    expect(state.api.saveKnowledgeMarkdown).toHaveBeenLastCalledWith(
      "set-1",
      { expected_version_seq: 4, markdown: "# Kept draft" },
      expect.objectContaining({ idempotency: expect.any(Object) }),
    );
  });

  it("shows a safe failure without an additional provider-confirmation action", async () => {
    state.role = "teacher";
    state.userId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
    sessionStorage.setItem(
      'maya:brainform-generation-job:["cccccccc-cccc-4ccc-8ccc-cccccccccccc","teacher","course-1"]:set-1',
      "stale-job",
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
        generation_job_id: "job-1",
        generation_state: "failed",
        safe_error_code: "provider_confirmation_required",
      },
    ]);
    renderWorkspace("teacher");

    expect(
      await screen.findByText("Generation did not complete."),
    ).toBeTruthy();
    expect(
      screen.queryByRole("link", { name: "Open provider disclosure" }),
    ).toBeNull();
    await waitFor(() =>
      expect(state.api.knowledgeGenerationJob).toHaveBeenCalledWith("job-1"),
    );
  });

  it("closes a failed generation notice with its × without touching the server", async () => {
    state.role = "teacher";
    state.userId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
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
        generation_job_id: null,
        generation_state: "failed",
        safe_error_code: "acceptance_unknown",
      },
    ]);
    renderWorkspace("teacher");

    const message = await screen.findByText(
      "Generation did not complete: acceptance unknown.",
    );
    const alert = message.closest('[role="alert"]') as HTMLElement;
    expect(alert).toBeTruthy();
    const mutations = [state.api.saveKnowledgeMarkdown].map(
      (mock) => mock.mock.calls.length,
    );
    fireEvent.click(within(alert).getByRole("button", { name: "Dismiss" }));
    expect(
      screen.queryByText("Generation did not complete: acceptance unknown."),
    ).toBeNull();
    expect(
      [state.api.saveKnowledgeMarkdown].map((mock) => mock.mock.calls.length),
    ).toEqual(mutations);
  });

  it("keeps a readable Knowledge version editable after a failed generation attempt", async () => {
    state.role = "teacher";
    state.userId = "ffffffff-ffff-4fff-8fff-ffffffffffff";
    state.api.brainformKnowledge.mockResolvedValue([
      {
        agent_id: "agent-1",
        canonical_set_id: "set-1",
        source_agent_display_name: "Socrates",
        knowledge_display_name: "Previous Knowledge",
        can_read: true,
        can_edit: true,
        version_seq: 2,
        content_hash: "d".repeat(64),
        generation_state: "failed",
        safe_error_code: "generation_failed",
      },
    ]);
    state.api.knowledgeMarkdown.mockResolvedValueOnce({
      audience: "full",
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Previous Knowledge",
      version_seq: 2,
      content_hash: "d".repeat(64),
      markdown: "# Previous readable version",
      projection_available: true,
      can_read: true,
      can_edit: true,
      created_at: "2026-10-05T00:00:00Z",
    });
    state.api.saveKnowledgeMarkdown.mockResolvedValue({
      audience: "full",
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Previous Knowledge",
      version_seq: 3,
      content_hash: "e".repeat(64),
      markdown: "# Teacher edit",
      projection_available: true,
      can_read: true,
      can_edit: true,
      created_at: "2026-10-06T00:00:00Z",
    });
    renderWorkspace("teacher");

    const editor = await openKnowledgeEditor("Previous Knowledge");
    expect(editor.value).toBe("# Previous readable version");
    fireEvent.change(editor, { target: { value: "# Teacher edit" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() =>
      expect(state.api.saveKnowledgeMarkdown).toHaveBeenCalledWith(
        "set-1",
        { expected_version_seq: 2, markdown: "# Teacher edit" },
        expect.objectContaining({ idempotency: expect.any(Object) }),
      ),
    );
  });

  it("hydrates a current generation failure without showing extra confirmation UI", async () => {
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
        version_seq: 2,
        content_hash: "b".repeat(64),
        generation_state: "blocked",
        safe_error_code: "provider_confirmation_required",
        generation_job_id: "job-2",
      },
    ]);
    state.api.knowledgeGenerationJob.mockResolvedValue({
      run_id: "run-2",
      job_id: "job-2",
      knowledge_set_id: "set-1",
      state: "blocked",
      provider_manifest_hash: "c".repeat(64),
      safe_error_code: "provider_confirmation_required",
      accepted_item_count: 0,
      materialized_item_count: 0,
      failed_item_count: 0,
      created_at: "2026-10-05T00:00:00Z",
      updated_at: "2026-10-05T00:00:00Z",
    });

    renderWorkspace("teacher");

    expect(
      await screen.findByText("Generation did not complete."),
    ).toBeTruthy();
    expect(
      screen.queryByRole("link", { name: "Open provider disclosure" }),
    ).toBeNull();
    expect(state.api.knowledgeGenerationJob).toHaveBeenCalledWith("job-2");
  });

  it("keeps a late old Job response from replacing the newer generation status", async () => {
    state.role = "teacher";
    state.userId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
    state.api.workspaceDocuments.mockResolvedValue([source]);
    const row = (
      jobId: string,
      generationState: "running" | "blocked",
      safeErrorCode: string | null,
    ) => ({
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      can_read: true,
      can_edit: true,
      version_seq: 2,
      content_hash: "b".repeat(64),
      generation_job_id: jobId,
      generation_state: generationState,
      safe_error_code: safeErrorCode,
    });
    state.api.brainformKnowledge
      .mockResolvedValueOnce([row("job-1", "running", null)])
      .mockResolvedValue([
        row("job-2", "blocked", "provider_confirmation_required"),
      ]);
    state.api.replaceKnowledgeDocument.mockResolvedValue({
      ...source,
      content_hash: "c".repeat(64),
      index_revision: 5,
      source_filename: "lesson.md",
    });
    let finishOldJob!: (status: object) => void;
    state.api.knowledgeGenerationJob.mockImplementation((jobId: string) => {
      if (jobId === "job-1") {
        return new Promise((resolve) => {
          finishOldJob = resolve;
        });
      }
      return Promise.resolve({
        run_id: "run-2",
        job_id: "job-2",
        knowledge_set_id: "set-1",
        state: "blocked",
        provider_manifest_hash: "d".repeat(64),
        safe_error_code: "provider_confirmation_required",
        accepted_item_count: 0,
        materialized_item_count: 0,
        failed_item_count: 0,
        created_at: "2026-10-05T00:00:00Z",
        updated_at: "2026-10-05T00:00:00Z",
      });
    });

    renderWorkspace("teacher");
    await waitFor(() =>
      expect(state.api.knowledgeGenerationJob).toHaveBeenCalledWith("job-1"),
    );
    const editButtons = await screen.findAllByRole("button", {
      name: "Edit lesson.md",
    });
    fireEvent.click(editButtons[0]);
    const editor = await screen.findByRole("textbox", {
      name: "Content",
    });
    fireEvent.change(editor, { target: { value: "# Updated lesson\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() =>
      expect(state.api.replaceKnowledgeDocument).toHaveBeenCalledTimes(1),
    );
    await waitFor(() =>
      expect(state.api.knowledgeGenerationJob).toHaveBeenCalledWith("job-2"),
    );
    // Done already closes the editor; the list shows the newer Job's status.
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Content" })).toBeNull(),
    );
    expect(
      await screen.findByText("Generation did not complete."),
    ).toBeTruthy();
    expect(
      screen.queryByRole("link", { name: "Open provider disclosure" }),
    ).toBeNull();

    await act(async () => {
      finishOldJob({
        run_id: "run-1",
        job_id: "job-1",
        knowledge_set_id: "set-1",
        state: "blocked",
        provider_manifest_hash: "a".repeat(64),
        safe_error_code: "provider_confirmation_required",
      });
    });
    expect(
      screen.queryByRole("link", { name: "Open provider disclosure" }),
    ).toBeNull();
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

    await screen.findByText("Socrates Knowledge");
    fireEvent.doubleClick(screen.getByText("Socrates Knowledge"));
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
