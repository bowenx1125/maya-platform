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
        <button onClick={actions.new.onClick} disabled={actions.new.disabled}>
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
      <ActionsHost>
        <BrainformWorkspace role={role as "teacher" | "student"} />
      </ActionsHost>
    </LocaleProvider>,
  );
}

async function openKnowledgeEditor(name: string) {
  fireEvent.click(await screen.findByRole("button", { name: `Open ${name}` }));
  await screen.findByRole("region", { name: "Agents using this Knowledge" });
  expect(
    screen.queryByRole("textbox", { name: "Markdown content" }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "New" }));
  return (await screen.findByRole("textbox", {
    name: "Markdown content",
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
    expect(input.getAttribute("accept")).toContain(".md");
    expect(input.getAttribute("accept")).toContain(".pdf");
    expect(input.getAttribute("accept")).toContain(".docx");
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => {
      const content = screen.getByRole("textbox", {
        name: "Markdown content",
      }) as HTMLTextAreaElement;
      expect(content.value).toBe(markdown);
    });
    expect(state.api.createWorkspaceKnowledge).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Done" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
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

  it("creates a Student RAG source through the explicitly joined Group route", async () => {
    state.role = "student";
    state.userId = "66666666-6666-4666-8666-666666666666";
    state.groups = [{ group_id: "group-1" }];
    const groupDocument = {
      ...source,
      id: "group-document-1",
      group_id: "group-1",
      ownership_scope: "group",
      visibility: "public",
    };
    state.api.knowledge.mockResolvedValue([]);
    state.api.createLibraryKnowledge = vi.fn().mockResolvedValue({
      document: groupDocument,
      agent_version: null,
    });
    renderWorkspace("student");
    await waitFor(() =>
      expect(state.api.knowledge).toHaveBeenCalledWith("group-1"),
    );
    expect(state.api.workspaceDocuments).not.toHaveBeenCalled();

    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "New" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Markdown content" }),
      {
        target: { value: "# Group evidence" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() =>
      expect(state.api.createLibraryKnowledge).toHaveBeenCalledTimes(1),
    );
    expect(state.api.createLibraryKnowledge).toHaveBeenCalledWith(
      "group-1",
      expect.objectContaining({ name: "notes.md" }),
      expect.objectContaining({ idempotency: expect.any(Object) }),
    );
    expect(state.api.workspaceDocuments).not.toHaveBeenCalled();
  });

  it("keeps PDF bytes intact until the sidebar Done action submits the new RAG file", async () => {
    state.role = "teacher";
    renderWithActions({ role: "teacher", initialMode: "rag-new" });
    const file = new File(
      [new Uint8Array([0, 1, 2, 127, 128, 255])],
      "archive.pdf",
      { type: "application/pdf" },
    );
    fireEvent.change(await screen.findByLabelText("Import a file"), {
      target: { files: [file] },
    });
    expect(
      await screen.findByText(
        "archive.pdf is selected. It will be imported when you save.",
      ),
    ).toBeTruthy();
    expect(state.api.createWorkspaceKnowledge).not.toHaveBeenCalled();

    const done = () => screen.getByRole("button", { name: "Done" });
    await waitFor(() =>
      expect((done() as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(done());
    await waitFor(() =>
      expect(state.api.createWorkspaceKnowledge).toHaveBeenCalledTimes(1),
    );
    const upload = state.api.createWorkspaceKnowledge.mock.calls[0][1] as File;
    expect(upload.name).toBe("archive.pdf");
    const savedBytes = await new Promise<Uint8Array>((resolve) => {
      const reader = new FileReader();
      reader.onload = () =>
        resolve(new Uint8Array(reader.result as ArrayBuffer));
      reader.readAsArrayBuffer(upload);
    });
    expect([...savedBytes]).toEqual([0, 1, 2, 127, 128, 255]);
  });

  it("reuses an uncertain binary save key only for the same filename and bytes", async () => {
    state.role = "teacher";
    const keys: string[] = [];
    state.api.createWorkspaceKnowledge = vi.fn(
      async (
        _courseId: string,
        file: File,
        options: { idempotency: { key: string } },
      ) => {
        keys.push(options.idempotency.key);
        if (keys.length < 4) throw new TypeError("connection reset");
        return { document: { ...source, source_filename: file.name } };
      },
    );
    renderWithActions({ role: "teacher", initialMode: "rag-new" });
    const input = await screen.findByLabelText("Import a file");
    const done = () => screen.getByRole("button", { name: "Done" });
    const selectAndWait = async (file: File) => {
      fireEvent.change(input, { target: { files: [file] } });
      await waitFor(() =>
        expect((done() as HTMLButtonElement).disabled).toBe(false),
      );
    };
    const saveAndWait = async (callCount: number) => {
      fireEvent.click(done());
      await waitFor(() =>
        expect(state.api.createWorkspaceKnowledge).toHaveBeenCalledTimes(
          callCount,
        ),
      );
      if (callCount < 4) {
        await waitFor(() =>
          expect((done() as HTMLButtonElement).disabled).toBe(false),
        );
      }
    };

    await selectAndWait(binaryUpload("archive.pdf", [1, 2, 3, 4], 456));
    await saveAndWait(1);
    await selectAndWait(binaryUpload("archive.pdf", [1, 2, 3, 4]));
    await saveAndWait(2);
    expect(keys[1]).toBe(keys[0]);

    await selectAndWait(binaryUpload("archive.pdf", [1, 2, 3, 5]));
    await saveAndWait(3);
    expect(keys[2]).not.toBe(keys[1]);

    await selectAndWait(binaryUpload("renamed.pdf", [1, 2, 3, 5]));
    await saveAndWait(4);
    expect(keys[3]).not.toBe(keys[2]);
  });

  it("reuses a create key for the same uncertain save and rotates after draft edits", async () => {
    state.role = "teacher";
    state.userId = "11111111-1111-4111-8111-111111111111";
    const keys: string[] = [];
    state.api.createWorkspaceKnowledge = vi.fn(
      async (
        _courseId: string,
        file: File,
        options: { idempotency: { key: string } },
      ) => {
        keys.push(options.idempotency.key);
        if (keys.length < 3) throw new TypeError("connection reset");
        return { document: { ...source, source_filename: file.name } };
      },
    );
    renderWithActions();
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "New" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    const content = screen.getByRole("textbox", { name: "Markdown content" });
    fireEvent.change(content, { target: { value: "# First attempt" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(state.api.createWorkspaceKnowledge).toHaveBeenCalledTimes(1),
    );

    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Done" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(state.api.createWorkspaceKnowledge).toHaveBeenCalledTimes(2),
    );
    expect(keys[1]).toBe(keys[0]);

    fireEvent.change(content, { target: { value: "# Changed draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(state.api.createWorkspaceKnowledge).toHaveBeenCalledTimes(3),
    );
    expect(keys[2]).not.toBe(keys[1]);
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
      (await screen.findAllByRole("button", { name: "Edit lesson.md" }))[1],
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
      name: "Markdown content",
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
    expect(viewButtons).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Edit lesson.md" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Hide lesson.md" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Reindex lesson.md" }),
    ).toBeNull();
    fireEvent.click(viewButtons[1]);
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
    expect(await screen.findByText("refresh unavailable")).toBeTruthy();
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
    expect(await screen.findByText("refresh unavailable")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(state.api.workspaceDocuments.mock.calls.length).toBeGreaterThan(1),
    );
    expect(state.api.reindex).toHaveBeenCalledTimes(1);
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
    const unsupported = markdownUpload(
      "wrong.txt",
      Promise.resolve(new ArrayBuffer(0)),
    );
    fireEvent.change(screen.getByLabelText("Import a file"), {
      target: { files: [unsupported] },
    });
    expect(screen.getByDisplayValue("# Keep my draft")).toBeTruthy();
    expect(state.api.createWorkspaceKnowledge).not.toHaveBeenCalled();
  });

  it("does not let a file read from the previous identity overwrite a new actor draft", async () => {
    state.role = "teacher";
    const view = renderWithActions();
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
    state.userId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
    view.rerender(
      <LocaleProvider initialLocale="en">
        <ActionsHost>
          <BrainformWorkspace role="teacher" />
        </ActionsHost>
      </LocaleProvider>,
    );
    await waitFor(() => {
      expect(
        (screen.getByRole("button", { name: "New" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false);
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
        name: "Open Socrates memory in Chatform",
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

  it("groups canonical Knowledge once and lists its readable Agent users in the independent detail view", async () => {
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

    expect(await screen.findByText("Used by: Socrates, Mencius")).toBeTruthy();
    expect(
      screen.getAllByRole("button", { name: "Rename Shared notes" }),
    ).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Open Shared notes" }));

    const usage = await screen.findByRole("region", {
      name: "Agents using this Knowledge",
    });
    expect(within(usage).getByText("Socrates")).toBeTruthy();
    expect(within(usage).getByText("Mencius")).toBeTruthy();
    expect(state.api.knowledgeMarkdown).toHaveBeenCalledWith("set-1");
  });

  it("shows a running Knowledge by name with a busy enter button until it completes", async () => {
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
      screen.queryByRole("button", { name: "Open Question bank" }),
    ).toBeNull();

    expect(
      await screen.findByRole("button", { name: "Open Question bank" }),
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
      await screen.findByRole("button", { name: "Open Empty Knowledge" }),
    );
    expect(
      await screen.findByText(
        "No Knowledge version is published yet. This is an empty Markdown draft.",
      ),
    ).toBeTruthy();
    const editor = screen.getByRole("textbox", { name: "Markdown content" });
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
    expect(state.api.regenerateKnowledgeMarkdown).not.toHaveBeenCalled();
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

  it("keeps the canonical editor read-only while its publish is pending, then shows the published view", async () => {
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
    expect(
      await screen.findByText("Knowledge published as a new version."),
    ).toBeTruthy();
    expect(
      screen.queryByRole("textbox", { name: "Markdown content" }),
    ).toBeNull();
    expect(screen.getByRole("heading", { name: "Sent body" })).toBeTruthy();
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
    expect(state.api.regenerateKnowledgeMarkdown).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(state.api.knowledgeGenerationJob).toHaveBeenCalledWith("job-1"),
    );
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
    expect(state.api.regenerateKnowledgeMarkdown).not.toHaveBeenCalled();
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
    expect(state.api.regenerateKnowledgeMarkdown).not.toHaveBeenCalled();
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
    fireEvent.click(editButtons[1]);
    const editor = await screen.findByRole("textbox", {
      name: "Markdown content",
    });
    fireEvent.change(editor, { target: { value: "# Updated lesson\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() =>
      expect(state.api.replaceKnowledgeDocument).toHaveBeenCalledTimes(1),
    );
    await waitFor(() =>
      expect(state.api.knowledgeGenerationJob).toHaveBeenCalledWith("job-2"),
    );
    await screen.findByRole("button", { name: "Back" });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
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
    expect(state.api.regenerateKnowledgeMarkdown).not.toHaveBeenCalled();
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
