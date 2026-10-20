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
import { AppShell } from "../components/app-shell";
import { buildAgentTemplate } from "../components/agent-template";
import { LanguageSwitcher, LocaleProvider } from "../components/locale";
import { SessionProvider, useSession } from "../components/session-provider";
import type {
  AgentDetail,
  AgentVersion,
  AuthSession,
  KnowledgeDocument,
  PlatformApi,
  RagPreview,
  VoiceProfile,
} from "../lib/api";
import { PlatformApiError } from "../lib/api";

const navigation = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
  usePathname: () => "/student/agent-versions/version-id/edit",
}));

// Keep the integration test on the real AgentWorkbench/SessionProvider path
// without requiring a WebGL context from jsdom.
vi.mock("../components/avatar/avatar-canvas", () => ({
  AvatarCanvas: ({
    fallbackLabel,
    state,
  }: {
    fallbackLabel?: string;
    state?: string;
  }) => (
    <div role="img" data-avatar-state={state}>
      {fallbackLabel}
    </div>
  ),
}));

type IdentitySnapshot = {
  api: unknown;
  session: AuthSession | null;
  csrf: string | null;
  locale: string;
};

function IdentityProbe({
  onChange,
}: {
  onChange: (value: IdentitySnapshot) => void;
}) {
  const sessionState = useSession();
  const locale = document.documentElement.lang;
  onChange({
    api: sessionState.api,
    session: sessionState.session,
    csrf: sessionState.api.getCsrfToken() ?? null,
    locale,
  });
  return null;
}

function makeDocument(): KnowledgeDocument {
  return {
    id: "document-id",
    group_id: "group-id",
    course_id: "course-id",
    ownership_scope: "group",
    visibility: "public",
    can_manage_visibility: false,
    authorization_epoch: 0,
    source_filename: "evidence.md",
    source_owner_role: "student",
    content_hash: "a".repeat(64),
    created_at: "2026-10-04T00:00:00Z",
    index_revision: 0,
    char_count: 42,
    workspace_state: "active",
    index_status: "ready",
  } as KnowledgeDocument;
}

function makeVersion(overrides: Partial<AgentVersion> = {}): AgentVersion {
  return {
    id: "version-id",
    agent_id: "agent-id",
    version_label: "V1.0",
    state: "draft",
    revision: 0,
    agent_md: "# Server Agent",
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
    knowledge_snapshot_id: null,
    enabled_documents: [],
    publish_blockers: [],
    ...overrides,
  } as AgentVersion;
}

function makeAgent(): AgentDetail {
  return {
    id: "agent-id",
    group_id: "group-id",
    course_id: "course-id",
    ownership_scope: "group",
    visibility: "public",
    can_edit: true,
    name: "Agent",
    description: "A stable Agent description",
    metadata_revision: 0,
    status: "active",
    current_draft_version_id: "version-id",
    current_published_version_id: null,
    versions: [],
  } as AgentDetail;
}

function makeSession(): AuthSession {
  return {
    csrf_token: "csrf-1",
    expires_at: "2026-08-27T12:00:00Z",
    user: {
      id: "student-id",
      username: "student",
      display_name: "Student",
      courses: [{ course_id: "course-id", role: "student" }],
      groups: [{ group_id: "group-id", role: "member" }],
    },
  } as AuthSession;
}

function makePreview(): RagPreview {
  return {
    version_id: "version-id",
    total_char_count: 42,
    limit: null,
    document_count: 1,
    index_status: "ready",
    combined_markdown: "# Evidence\n\nA stable source excerpt.",
  } as RagPreview;
}

function makeTemplates() {
  return [
    {
      id: "wave1-default-head",
      name: "Wave 1 Default Head",
      available: true,
      supported_parameters: ["template_id", "material_theme"],
    },
    {
      id: "maya-warm-scholar",
      name: "Maya Warm Scholar",
      available: true,
      supported_parameters: ["template_id", "material_theme"],
    },
    {
      id: "maya-civic-observer",
      name: "Maya Civic Observer",
      available: true,
      supported_parameters: ["template_id", "material_theme"],
    },
  ];
}

function makeApi() {
  const version = makeVersion();
  const agent = makeAgent();
  const document = makeDocument();
  const api = {
    me: vi.fn(async () => makeSession()),
    getCsrfToken: vi.fn(() => "csrf-1"),
    version: vi.fn(async () => version),
    agent: vi.fn(async () => agent),
    knowledge: vi.fn(async () => [document]),
    knowledgeSets: vi.fn(async () => []),
    agentKnowledgeSets: vi.fn(async () => ({
      agent_id: agent.id,
      agent_metadata_revision: agent.metadata_revision,
      sets: [],
    })),
    replaceAgentKnowledgeSets: vi.fn(
      async (
        _agentId: string,
        body: { expected_agent_metadata_revision: number },
      ) => ({
        agent_id: agent.id,
        agent_metadata_revision: body.expected_agent_metadata_revision + 1,
        sets: [],
      }),
    ),
    ragPreview: vi.fn(async () => makePreview()),
    avatarTemplates: vi.fn(async () => makeTemplates()),
    voiceProfiles: vi.fn(async (): Promise<VoiceProfile[]> => []),
    updateDraft: vi.fn(async (..._args: unknown[]) => version),
    uploadKnowledge: vi.fn(async (..._args: unknown[]) => ({
      agent_version: version,
      document,
    })),
    setDocuments: vi.fn(async () =>
      makeVersion({
        revision: 1,
        enabled_documents: [document],
      }),
    ),
    publish: vi.fn(),
    testChat: vi.fn(),
  };
  return { api, version, document };
}

function renderWorkbench(
  api: PlatformApi,
  onIdentityChange: (value: IdentitySnapshot) => void,
) {
  return render(
    <LocaleProvider initialLocale="en">
      <SessionProvider api={api}>
        <IdentityProbe onChange={onIdentityChange} />
        <LanguageSwitcher />
        <AppShell role="student">
          <AgentWorkbench versionId="version-id" />
        </AppShell>
      </SessionProvider>
    </LocaleProvider>,
  );
}

describe("Wave 1C real workbench locale boundary", () => {
  afterEach(() => {
    cleanup();
    navigation.push.mockReset();
    navigation.replace.mockReset();
    vi.restoreAllMocks();
  });

  it("saves local edits before Done publishes the returned revision", async () => {
    const { api } = makeApi();
    const saved = makeVersion({ revision: 1, agent_md: "# Local Agent" });
    api.updateDraft.mockResolvedValue(saved);
    api.agent
      .mockResolvedValueOnce(makeAgent())
      .mockResolvedValue({ ...makeAgent(), name: "Local Agent" });
    api.publish.mockResolvedValue({ ...saved, state: "published" });
    renderWorkbench(api as unknown as PlatformApi, () => undefined);

    await screen.findByRole("button", { name: "Done" });
    const editor = screen.getByLabelText("AGENT.md editor");
    fireEvent.change(editor, { target: { value: "# Local Agent" } });
    expect(screen.queryByText("Unsaved local changes")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(api.publish).toHaveBeenCalledWith(
        "version-id",
        1,
        expect.anything(),
      ),
    );
    expect(api.updateDraft).toHaveBeenCalledWith(
      "version-id",
      expect.objectContaining({
        expected_revision: 0,
        agent_md: "# Local Agent",
      }),
    );
    expect(api.updateDraft.mock.invocationCallOrder[0]).toBeLessThan(
      api.publish.mock.invocationCallOrder[0],
    );
    expect(api.agent).toHaveBeenCalledTimes(2);
    expect(
      screen.getByRole("heading", { name: "Local Agent · V1.0" }),
    ).toBeTruthy();
    expect(navigation.replace).toHaveBeenCalledWith("/student/agents/agent-id");
    expect(screen.queryByRole("button", { name: "Publish" })).toBeNull();
  });

  it("does not infer a generation intent from already-selected courseware", async () => {
    const { api, document } = makeApi();
    const withSource = makeVersion({ enabled_documents: [document] });
    api.version.mockResolvedValue(withSource);
    api.publish.mockResolvedValue({ ...withSource, state: "published" });
    renderWorkbench(api as unknown as PlatformApi, () => undefined);

    fireEvent.click(await screen.findByRole("button", { name: "Done" }));
    await waitFor(() => expect(api.publish).toHaveBeenCalled());
    expect(api.publish).toHaveBeenCalledWith(
      "version-id",
      withSource.revision,
      expect.not.objectContaining({ generation: expect.anything() }),
    );
  });

  it.each(["own-ready", ""])(
    "changes a later draft voice to %s without editing the published version",
    async (choice) => {
      const { api } = makeApi();
      const draft = makeVersion({
        version_label: "V1.1",
        voice_profile_id: "inherited-private",
      });
      const ownVoice = {
        id: "own-ready",
        source_filename: "My voice",
        status: "ready",
      } as VoiceProfile;
      api.version.mockResolvedValue(draft);
      api.voiceProfiles.mockResolvedValue([
        ownVoice,
        {
          ...ownVoice,
          id: "unfinished",
          status: "preview_ready",
          source_filename: "Not confirmed",
        },
      ]);
      const saved = { ...draft, revision: 1, voice_profile_id: choice || null };
      api.updateDraft.mockResolvedValue(saved);
      api.publish.mockResolvedValue({ ...saved, state: "published" });
      renderWorkbench(api as unknown as PlatformApi, () => undefined);
      // The inherited binding is not listed, so it shows as the checked
      // "Current voice" row until another row, None included, is chosen.
      expect(
        (
          (await screen.findByRole("radio", {
            name: "Current voice",
          })) as HTMLInputElement
        ).checked,
      ).toBe(true);
      // The voice list loads after the inherited binding is painted. Waiting
      // here keeps the unfinished profile from being read before it exists.
      expect(
        (
          (await screen.findByRole("radio", {
            name: "Not confirmed",
          })) as HTMLInputElement
        ).disabled,
      ).toBe(true);
      if (choice) {
        fireEvent.click(screen.getByRole("radio", { name: "My voice" }));
      } else {
        fireEvent.click(screen.getByRole("radio", { name: "None" }));
      }
      fireEvent.click(screen.getByRole("button", { name: "Done" }));
      await waitFor(() =>
        expect(api.publish).toHaveBeenCalledWith(
          "version-id",
          1,
          expect.anything(),
        ),
      );
      expect(api.updateDraft).toHaveBeenCalledWith(
        "version-id",
        expect.objectContaining({ voice_profile_id: choice || null }),
      );
      expect(draft.voice_profile_id).toBe("inherited-private");
    },
  );

  it("keeps an inherited voice untouched when only the next draft text changes", async () => {
    const { api } = makeApi();
    const draft = makeVersion({
      version_label: "V1.1",
      voice_profile_id: "inherited-private",
    });
    const saved = { ...draft, revision: 1, agent_md: "# Changed" };
    api.version.mockResolvedValue(draft);
    api.updateDraft.mockResolvedValue(saved);
    api.publish.mockResolvedValue({ ...saved, state: "published" });
    renderWorkbench(api as unknown as PlatformApi, () => undefined);
    const editor = await screen.findByLabelText("AGENT.md editor");
    fireEvent.change(editor, { target: { value: "# Changed" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(api.publish).toHaveBeenCalledTimes(1));
    expect(api.updateDraft.mock.calls[0][1]).not.toHaveProperty(
      "voice_profile_id",
    );
  });

  it("refreshes available voices on focus without discarding the next draft", async () => {
    const { api } = makeApi();
    renderWorkbench(api as unknown as PlatformApi, () => undefined);
    const editor = await screen.findByLabelText("AGENT.md editor");
    fireEvent.change(editor, { target: { value: "# Unsaved" } });
    api.voiceProfiles.mockResolvedValue([
      {
        id: "new-ready",
        source_filename: "New voice",
        status: "ready",
      } as VoiceProfile,
    ]);
    fireEvent.focus(window);
    expect(
      await screen.findByRole("radio", { name: "New voice" }),
    ).toBeTruthy();
    expect(editor).toHaveProperty("value", "# Unsaved");
  });

  it("shows a name conflict as an actionable error while retaining the local draft", async () => {
    const { api } = makeApi();
    api.updateDraft.mockRejectedValue(
      new PlatformApiError(409, "Conflict", { code: "agent_name_conflict" }),
    );
    renderWorkbench(api as unknown as PlatformApi, () => undefined);
    const editor = await screen.findByLabelText("AGENT.md editor");
    fireEvent.change(editor, { target: { value: "# Duplicate" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      expect.stringContaining(
        "This name is already in use. Please choose another name",
      ),
    );
    expect(editor).toHaveProperty("value", "# Duplicate");
    expect(api.publish).not.toHaveBeenCalled();
  });

  it("keeps Done from publishing when saving introduces new server blockers", async () => {
    const { api } = makeApi();
    api.updateDraft.mockResolvedValue(
      makeVersion({
        revision: 1,
        agent_md: "# Local Agent",
        publish_blockers: ["rag_index_pending"],
      }),
    );
    renderWorkbench(api as unknown as PlatformApi, () => undefined);
    await screen.findByRole("button", { name: "Done" });
    fireEvent.change(screen.getByLabelText("AGENT.md editor"), {
      target: { value: "# Local Agent" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Done" }) as HTMLButtonElement)
          .disabled,
      ).toBe(true),
    );
    expect(api.updateDraft).toHaveBeenCalledTimes(1);
    expect(api.publish).not.toHaveBeenCalled();
    expect(
      within(screen.getByRole("main")).getByRole("heading", {
        name: "Brainform",
      }),
    ).toBeTruthy();
    expect(screen.getByLabelText("AGENT.md editor")).toHaveProperty(
      "value",
      "# Local Agent",
    );
  });

  it("accepts free Markdown without a Persona or Test Chat step", async () => {
    const { api } = makeApi();
    api.updateDraft.mockResolvedValue(
      makeVersion({ revision: 1, agent_md: "# Local Agent" }),
    );
    api.publish.mockResolvedValue(
      makeVersion({ state: "published", revision: 2 }),
    );
    renderWorkbench(api as unknown as PlatformApi, () => undefined);
    await screen.findByRole("button", { name: "Done" });
    fireEvent.change(screen.getByLabelText("AGENT.md editor"), {
      target: { value: "# Local Agent" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(api.publish).toHaveBeenCalledWith(
        "version-id",
        1,
        expect.anything(),
      ),
    );
    expect(api.updateDraft.mock.invocationCallOrder[0]).toBeLessThan(
      api.publish.mock.invocationCallOrder[0],
    );
    expect(screen.queryByRole("heading", { name: "Persona" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Compile" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Test Chat" })).toBeNull();
  });

  it("leads the page with Back and asks before discarding local edits", async () => {
    const { api } = makeApi();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWorkbench(api as unknown as PlatformApi, () => undefined);
    const back = await screen.findByRole("link", { name: "Back" });
    fireEvent.change(screen.getByLabelText("AGENT.md editor"), {
      target: { value: "# Unsaved" },
    });
    expect(back.closest("nav")).not.toBeNull();
    expect(back.closest("main")).toBeNull();
    expect(back.getAttribute("href")).toBe("/student/agents/agent-id");
    expect(fireEvent.click(back)).toBe(false);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(api.updateDraft).not.toHaveBeenCalled();
  });

  it("inserts the free Markdown template in the selected language", async () => {
    const { api } = makeApi();
    renderWorkbench(api as unknown as PlatformApi, () => undefined);

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Switch to Chinese" }),
      ).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Switch to Chinese" }));
    fireEvent.click(screen.getByRole("button", { name: "模板" }));

    expect(
      (screen.getByLabelText("AGENT.md 编辑器") as HTMLTextAreaElement).value,
    ).toBe(buildAgentTemplate("Agent", "zh"));
    expect(
      (screen.getByLabelText("AGENT.md 编辑器") as HTMLTextAreaElement).value,
    ).toContain("# 我是谁");
    expect(
      (screen.getByLabelText("AGENT.md 编辑器") as HTMLTextAreaElement).value,
    ).not.toContain("# Identity");
  });

  // RAG files are uploaded in Brainform, not from this editor, so a locale
  // switch here only has to keep the session, selection and local edits.
  it("preserves API/session/CSRF, selected docs and local edits across locale switches", async () => {
    const identities: IdentitySnapshot[] = [];
    const { api } = makeApi();
    renderWorkbench(api as unknown as PlatformApi, (value) => {
      identities.push(value);
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Done" })).toBeTruthy(),
    );
    const countsBefore = {
      me: api.me.mock.calls.length,
      version: api.version.mock.calls.length,
      agent: api.agent.mock.calls.length,
      knowledge: api.knowledge.mock.calls.length,
      ragPreview: api.ragPreview.mock.calls.length,
      avatarTemplates: api.avatarTemplates.mock.calls.length,
      voiceProfiles: api.voiceProfiles.mock.calls.length,
    };
    const firstIdentity = identities.at(-1);

    const documentCheckbox = screen.getByRole("checkbox");
    fireEvent.click(documentCheckbox);
    await waitFor(() =>
      expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(
        true,
      ),
    );
    fireEvent.change(screen.getByLabelText("AGENT.md editor"), {
      target: { value: "# Local before switching" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Switch to Chinese" }));
    const lastIdentity = identities.at(-1);
    expect(lastIdentity?.api).toBe(firstIdentity?.api);
    expect(lastIdentity?.session).toBe(firstIdentity?.session);
    expect(lastIdentity?.csrf).toBe(firstIdentity?.csrf);
    expect(
      (screen.getByLabelText("AGENT.md 编辑器") as HTMLTextAreaElement).value,
    ).toBe("# Local before switching");
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(
      true,
    );
    expect(screen.getByText("evidence.md")).toBeTruthy();
    expect(screen.queryByText(/# Evidence/)).toBeNull();
    expect(screen.getByText("Agent · V1.0")).toBeTruthy();
    expect(api.me.mock.calls.length).toBe(countsBefore.me);
    expect(api.version.mock.calls.length).toBe(countsBefore.version);
    expect(api.agent.mock.calls.length).toBe(countsBefore.agent);
    expect(api.knowledge.mock.calls.length).toBe(countsBefore.knowledge);
    expect(api.avatarTemplates.mock.calls.length).toBe(
      countsBefore.avatarTemplates,
    );
    expect(api.voiceProfiles.mock.calls.length).toBe(
      countsBefore.voiceProfiles,
    );
    expect(api.uploadKnowledge).not.toHaveBeenCalled();
  });

  it("keeps a local AGENT.md and revision conflict visible after locale changes", async () => {
    const { api } = makeApi();
    api.updateDraft.mockImplementation(async () => {
      throw new PlatformApiError(409, "Draft changed", {
        code: "stale_revision",
      });
    });
    const identities: IdentitySnapshot[] = [];
    renderWorkbench(api as unknown as PlatformApi, (value) => {
      identities.push(value);
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Done" })).toBeTruthy(),
    );
    fireEvent.change(screen.getByLabelText("AGENT.md editor"), {
      target: { value: "# Conflict stays local" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "Your local AGENT.md",
      ),
    );
    const beforeSwitch = identities.at(-1);
    const countsBefore = {
      me: api.me.mock.calls.length,
      version: api.version.mock.calls.length,
      agent: api.agent.mock.calls.length,
      knowledge: api.knowledge.mock.calls.length,
      ragPreview: api.ragPreview.mock.calls.length,
    };

    fireEvent.click(screen.getByRole("button", { name: "Switch to Chinese" }));
    expect(
      (screen.getByLabelText("AGENT.md 编辑器") as HTMLTextAreaElement).value,
    ).toBe("# Conflict stays local");
    expect(screen.getByRole("alert").textContent).toContain(
      "本地 AGENT.md 仍保留",
    );
    expect(screen.getAllByText("版本冲突")).toHaveLength(1);
    const afterSwitch = identities.at(-1);
    expect(afterSwitch?.api).toBe(beforeSwitch?.api);
    expect(afterSwitch?.session).toBe(beforeSwitch?.session);
    expect(afterSwitch?.csrf).toBe(beforeSwitch?.csrf);
    expect(api.me.mock.calls.length).toBe(countsBefore.me);
    expect(api.version.mock.calls.length).toBe(countsBefore.version);
    expect(api.agent.mock.calls.length).toBe(countsBefore.agent);
    expect(api.knowledge.mock.calls.length).toBe(countsBefore.knowledge);
    expect(api.ragPreview.mock.calls.length).toBe(countsBefore.ragPreview);
    expect(api.updateDraft).toHaveBeenCalledTimes(1);
    expect(api.publish).not.toHaveBeenCalled();
  });
});
