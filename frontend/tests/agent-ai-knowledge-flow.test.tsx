import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentWorkbench } from "../components/agent-workspace";
import { AppShell } from "../components/app-shell";
import { LocaleProvider } from "../components/locale";
import { useSession } from "../components/session-provider";
import { TeacherAgentDetail } from "../components/teacher-workspace";
import type {
  AgentKnowledgeSets,
  AgentDetail,
  AgentVersion,
  KnowledgeDocument,
  KnowledgeSetDetail,
  KnowledgeSetSummary,
  ReplaceAgentKnowledgeSetsRequest,
} from "../lib/api";

const navigation = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
  usePathname: () => "/teacher/agents/agent-1?flow=ai-knowledge",
}));
vi.mock("../components/session-provider", () => ({ useSession: vi.fn() }));
vi.mock("../components/avatar/avatar-canvas", () => ({
  AvatarCanvas: () => <div role="img" aria-label="Agent avatar" />,
}));

const source: KnowledgeDocument = {
  id: "source-1",
  course_id: "course-1",
  group_id: null,
  ownership_scope: "personal",
  visibility: "private",
  can_manage_visibility: true,
  authorization_epoch: 0,
  source_filename: "lesson.md",
  char_count: 40,
  workspace_state: "active",
  index_status: "ready",
} as KnowledgeDocument;

const draft: AgentVersion = {
  id: "version-1",
  agent_id: "agent-1",
  version_label: "V1.0",
  state: "draft",
  revision: 0,
  agent_md: "# Teacher-created Agent",
  avatar_config: null,
  voice_profile_id: null,
  effective_voice_profile_id: null,
  voice_fallback_active: true,
  knowledge_snapshot_id: null,
  enabled_documents: [],
  publish_blockers: [],
} as unknown as AgentVersion;

const agent: AgentDetail = {
  id: "agent-1",
  group_id: null,
  course_id: "course-1",
  ownership_scope: "personal",
  visibility: "private",
  can_edit: true,
  name: "Teacher-created Agent",
  description: "",
  metadata_revision: 0,
  status: "active",
  current_draft_version_id: "version-1",
  current_published_version_id: null,
  versions: [],
} as AgentDetail;

const generatedSet = {
  id: "set-1",
  owner_user_id: "teacher-1",
  course_id: "course-1",
  group_id: null,
  ownership_scope: "personal",
  visibility: "private",
  display_name: "Generated Knowledge",
  metadata_revision: 0,
  content_revision: 0,
  authorization_epoch: 0,
  source_count: 1,
  asset_count: 1,
  can_edit: true,
  sources: [],
} as unknown as KnowledgeSetDetail;

function makeApi(enabledDocuments: KnowledgeDocument[] = []) {
  let currentVersion = {
    ...draft,
    enabled_documents: enabledDocuments,
  } as AgentVersion;
  return {
    personalVoiceProfiles: vi.fn(async () => []),
    version: vi.fn(async () => currentVersion),
    agent: vi.fn(async () => agent),
    versions: vi.fn(async () => []),
    knowledgeSet: vi.fn(async () => generatedSet),
    knowledgeSets: vi.fn(async (): Promise<KnowledgeSetSummary[]> => []),
    agentKnowledgeSets: vi.fn(async (): Promise<AgentKnowledgeSets> => ({
      agent_id: "agent-1",
      agent_metadata_revision: 0,
      sets: [],
    })),
    replaceAgentKnowledgeSets: vi.fn(
      async (
        _agentId: string,
        body: ReplaceAgentKnowledgeSetsRequest,
      ): Promise<AgentKnowledgeSets> => ({
        agent_id: "agent-1",
        agent_metadata_revision: body.expected_agent_metadata_revision + 1,
        sets: [],
      }),
    ),
    nextVersion: vi.fn(async () => draft),
    workspaceDocuments: vi.fn(async () => [source]),
    ragPreview: vi.fn(async () => ({
      version_id: "version-1",
      total_char_count: 40,
      limit: null,
      document_count: 0,
      index_status: "ready",
      combined_markdown: "",
    })),
    avatarTemplates: vi.fn(async () => []),
    updateDraft: vi.fn(
      async (_versionId: string, body: { agent_md?: string }) => {
        currentVersion = {
          ...currentVersion,
          revision: currentVersion.revision + 1,
          agent_md: body.agent_md ?? currentVersion.agent_md,
        } as AgentVersion;
        return currentVersion;
      },
    ),
    setDocuments: vi.fn(
      async (_versionId: string, _revision: number, ids: string[]) => {
        currentVersion = {
          ...draft,
          revision: 1,
          enabled_documents: ids.includes(source.id) ? [source] : [],
        } as AgentVersion;
        return currentVersion;
      },
    ),
    publish: vi.fn(
      async (
        _versionId: string,
        _revision: number,
        _options?: { generation?: { source_document_ids: string[] } },
      ) => ({
        ...currentVersion,
        state: "published",
        knowledge_generation: {
          run_id: "run-1",
          job_id: "job-1",
          knowledge_set_id: "set-1",
          state: "pending",
        },
      }),
    ),
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve: (value: T) => resolve(value) };
}

function renderWorkbench(
  api: ReturnType<typeof makeApi>,
  generationFlow: boolean,
) {
  vi.mocked(useSession).mockReturnValue({
    api,
    user: {
      id: "teacher-1",
      courses: [{ course_id: "course-1", role: "teacher" }],
      groups: [],
    },
    logout: vi.fn(),
  } as never);
  return render(
    <LocaleProvider initialLocale="en">
      <AppShell role="teacher">
        <AgentWorkbench versionId="version-1" generationFlow={generationFlow} />
      </AppShell>
    </LocaleProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.mocked(useSession).mockReset();
  navigation.replace.mockReset();
  vi.restoreAllMocks();
});

describe("explicit AI Knowledge Agent flow", () => {
  it("requires a Source before Done and then sends only the selected IDs", async () => {
    const api = makeApi();
    renderWorkbench(api, true);

    const done = await screen.findByRole("button", { name: "Done" });
    const editor = screen.getByRole("textbox", { name: "AGENT.md editor" });
    fireEvent.compositionStart(editor);
    fireEvent.change(editor, { target: { value: "# 中文教师 Agent" } });
    fireEvent.compositionEnd(editor, { data: "# 中文教师 Agent" });
    fireEvent.click(done);
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Choose at least one Source to continue.",
    );
    expect(api.publish).not.toHaveBeenCalled();

    const sourceCheckbox = screen.getByRole("checkbox", { name: /lesson\.md/ });
    sourceCheckbox.focus();
    fireEvent.keyDown(sourceCheckbox, { key: " " });
    fireEvent.click(sourceCheckbox, { detail: 0 });
    fireEvent.keyUp(sourceCheckbox, { key: " " });
    await waitFor(() =>
      expect((sourceCheckbox as HTMLInputElement).checked).toBe(true),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Done" })).not.toHaveProperty(
        "disabled",
        true,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(api.publish).toHaveBeenCalledTimes(1));
    expect(api.updateDraft).toHaveBeenCalledWith(
      "version-1",
      expect.objectContaining({ agent_md: "# 中文教师 Agent" }),
    );
    expect(api.publish).toHaveBeenCalledWith(
      "version-1",
      2,
      expect.objectContaining({
        generation: { source_document_ids: ["source-1"] },
      }),
    );
    expect(navigation.replace).toHaveBeenCalledWith(
      "/teacher/knowledge?agent_id=agent-1&set_id=set-1&job_id=job-1",
    );
  });

  it("does not send a generation intent in the ordinary Agent flow", async () => {
    const api = makeApi();
    renderWorkbench(api, false);
    fireEvent.click(
      await screen.findByRole("checkbox", { name: /lesson\.md/ }),
    );
    await waitFor(() => expect(api.setDocuments).toHaveBeenCalled());
    const done = await screen.findByRole("button", { name: "Done" });
    await waitFor(() => expect(done).not.toHaveProperty("disabled", true));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(api.publish).toHaveBeenCalledTimes(1));
    expect(api.publish.mock.calls[0]?.[2]).not.toHaveProperty("generation");
  });

  it("selects a Knowledge set from the Agent editor", async () => {
    const api = makeApi();
    api.knowledgeSets.mockResolvedValue([generatedSet as KnowledgeSetSummary]);
    renderWorkbench(api, false);

    fireEvent.click(
      await screen.findByRole("checkbox", { name: /Generated Knowledge/ }),
    );
    await waitFor(() =>
      expect(api.replaceAgentKnowledgeSets).toHaveBeenCalledWith(
        "agent-1",
        expect.objectContaining({ set_ids: ["set-1"] }),
        expect.anything(),
      ),
    );
  });

  it("starts from an existing Agent's saved Sources when Done is explicitly chosen", async () => {
    const api = makeApi([source]);
    renderWorkbench(api, true);
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));
    await waitFor(() => expect(api.publish).toHaveBeenCalledTimes(1));
    expect(api.publish).toHaveBeenCalledWith(
      "version-1",
      0,
      expect.objectContaining({
        generation: { source_document_ids: ["source-1"] },
      }),
    );
    expect(navigation.replace).toHaveBeenCalledWith(
      "/teacher/knowledge?agent_id=agent-1&set_id=set-1&job_id=job-1",
    );
  });

  it("opens an update on a new Agent draft and keeps the receipt's stable Set ID", async () => {
    const published = {
      ...draft,
      id: "published-version",
      state: "published",
      knowledge_generation: null,
    } as AgentVersion;
    const updateDraft = {
      ...draft,
      id: "update-draft",
      revision: 0,
    } as AgentVersion;
    const api = {
      ...makeApi(),
      agent: vi.fn(async () => ({
        ...agent,
        current_published_version_id: published.id,
      })),
      versions: vi.fn(async () => [published]),
      knowledgeSet: vi.fn(async () => ({
        ...generatedSet,
        generated_by_agent_id: "agent-1",
      })),
      nextVersion: vi.fn(async () => updateDraft),
      version: vi.fn(async () => published),
      updateDraft: vi.fn(async () => ({
        ...updateDraft,
        revision: 0,
        enabled_documents: [],
      })),
      setDocuments: vi.fn(
        async (_versionId: string, _revision: number, ids: string[]) => ({
          ...updateDraft,
          revision: 1,
          enabled_documents: ids.includes(source.id) ? [source] : [],
        }),
      ),
      publish: vi.fn(async () => ({
        ...updateDraft,
        revision: 1,
        state: "published",
        knowledge_generation: {
          run_id: "update-run",
          job_id: "update-job",
          knowledge_set_id: "set-1",
          state: "pending",
        },
      })),
    };
    vi.mocked(useSession).mockReturnValue({
      api,
      user: {
        id: "teacher-1",
        courses: [{ course_id: "course-1", role: "teacher" }],
        groups: [],
      },
      identityGeneration: 1,
      logout: vi.fn(),
    } as never);
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherAgentDetail
            agentId="agent-1"
            generationFlow
            generationSetId="set-1"
          />
        </AppShell>
      </LocaleProvider>,
    );

    const editor = await screen.findByRole("textbox", {
      name: "AGENT.md editor",
    });
    expect(api.nextVersion).not.toHaveBeenCalled();
    fireEvent.click(
      await screen.findByRole("checkbox", { name: /lesson\.md/ }),
    );
    expect(api.setDocuments).not.toHaveBeenCalled();
    const done = await screen.findByRole("button", { name: "Done" });
    await waitFor(() => expect(done).not.toHaveProperty("disabled", true));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(api.nextVersion).toHaveBeenCalledWith(
        "agent-1",
        expect.objectContaining({ idempotency: expect.any(Object) }),
      ),
    );
    await waitFor(() => expect(api.publish).toHaveBeenCalledTimes(1));
    expect(api.publish).toHaveBeenCalledWith(
      "update-draft",
      1,
      expect.objectContaining({
        generation: { source_document_ids: ["source-1"] },
      }),
    );
    expect(navigation.replace).toHaveBeenCalledWith(
      "/teacher/knowledge?agent_id=agent-1&set_id=set-1&job_id=update-job",
    );
    expect(editor).toBeTruthy();
  });

  it("rejects a guessed Set ID even if another Set names the same Agent", async () => {
    const published = {
      ...draft,
      id: "published-version",
      state: "published",
      knowledge_generation: null,
    } as AgentVersion;
    const api = {
      ...makeApi(),
      agent: vi.fn(async () => ({
        ...agent,
        current_published_version_id: published.id,
      })),
      versions: vi.fn(async () => [published]),
      knowledgeSet: vi.fn(async () => ({
        ...generatedSet,
        id: "different-set",
        generated_by_agent_id: "agent-1",
      })),
      nextVersion: vi.fn(async () => draft),
    };
    vi.mocked(useSession).mockReturnValue({
      api,
      user: {
        id: "teacher-1",
        courses: [{ course_id: "course-1", role: "teacher" }],
        groups: [],
      },
      identityGeneration: 1,
      logout: vi.fn(),
    } as never);
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherAgentDetail
            agentId="agent-1"
            generationFlow
            generationSetId="set-1"
          />
        </AppShell>
      </LocaleProvider>,
    );
    expect(
      await screen.findByText(/not linked to a generation receipt/),
    ).toBeTruthy();
    expect(api.knowledgeSet).toHaveBeenCalledWith("set-1");
    expect(api.nextVersion).not.toHaveBeenCalled();
  });

  it("rejects an Update when the Teacher has no writable owner projection", async () => {
    const published = {
      ...draft,
      id: "published-version",
      state: "published",
      knowledge_generation: null,
    } as AgentVersion;
    const api = {
      ...makeApi(),
      agent: vi.fn(async () => ({
        ...agent,
        current_published_version_id: published.id,
      })),
      versions: vi.fn(async () => [published]),
      knowledgeSet: vi.fn(async () => ({
        ...generatedSet,
        owner_user_id: null,
        can_edit: false,
        generated_by_agent_id: null,
      })),
      nextVersion: vi.fn(async () => draft),
    };
    vi.mocked(useSession).mockReturnValue({
      api,
      user: {
        id: "teacher-1",
        courses: [{ course_id: "course-1", role: "teacher" }],
        groups: [],
      },
      identityGeneration: 1,
      logout: vi.fn(),
    } as never);
    render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherAgentDetail
            agentId="agent-1"
            generationFlow
            generationSetId="set-1"
          />
        </AppShell>
      </LocaleProvider>,
    );
    expect(
      await screen.findByText(/not linked to a generation receipt/),
    ).toBeTruthy();
    expect(api.nextVersion).not.toHaveBeenCalled();
  });

  it("fences a late Set authorization lookup when the update target changes", async () => {
    const published = {
      ...draft,
      id: "published-version",
      state: "published",
      knowledge_generation: null,
    } as AgentVersion;
    const oldSetLookup = deferred<KnowledgeSetDetail>();
    const api = {
      ...makeApi(),
      agent: vi.fn(async () => ({
        ...agent,
        current_published_version_id: published.id,
      })),
      versions: vi.fn(async () => [published]),
      knowledgeSet: vi.fn((setId: string) =>
        setId === "set-old"
          ? oldSetLookup.promise
          : Promise.resolve({
              ...generatedSet,
              id: setId,
              generated_by_agent_id: "agent-1",
            }),
      ),
      nextVersion: vi.fn(async () => draft),
    };
    vi.mocked(useSession).mockReturnValue({
      api,
      user: {
        id: "teacher-1",
        courses: [{ course_id: "course-1", role: "teacher" }],
        groups: [],
      },
      identityGeneration: 1,
      logout: vi.fn(),
    } as never);
    const view = render(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherAgentDetail
            agentId="agent-1"
            generationFlow
            generationSetId="set-old"
          />
        </AppShell>
      </LocaleProvider>,
    );
    await waitFor(() =>
      expect(api.knowledgeSet).toHaveBeenCalledWith("set-old"),
    );
    view.rerender(
      <LocaleProvider initialLocale="en">
        <AppShell role="teacher">
          <TeacherAgentDetail
            agentId="agent-1"
            generationFlow
            generationSetId="set-new"
          />
        </AppShell>
      </LocaleProvider>,
    );
    await waitFor(() =>
      expect(api.knowledgeSet).toHaveBeenCalledWith("set-new"),
    );
    await act(async () => {
      oldSetLookup.resolve({
        ...generatedSet,
        id: "set-old",
        generated_by_agent_id: "agent-1",
      });
      await oldSetLookup.promise;
    });
    expect(
      await screen.findByRole("textbox", { name: "AGENT.md editor" }),
    ).toBeTruthy();
    expect(api.nextVersion).not.toHaveBeenCalled();
  });
});
