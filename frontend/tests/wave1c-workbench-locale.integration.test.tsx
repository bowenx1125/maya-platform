import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentWorkbench } from "../components/agent-workspace";
import { buildPersonaTemplate } from "../components/persona";
import { LanguageSwitcher, LocaleProvider } from "../components/locale";
import { SessionProvider, useSession } from "../components/session-provider";
import type {
  AgentDetail,
  AgentVersion,
  AuthSession,
  KnowledgeDocument,
  PlatformApi,
  RagPreview,
} from "../lib/api";
import { PlatformApiError } from "../lib/api";

const navigation = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
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
    source_filename: "evidence.md",
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
    limit: 100000,
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
    ragPreview: vi.fn(async () => makePreview()),
    avatarTemplates: vi.fn(async () => makeTemplates()),
    voiceProfiles: vi.fn(async () => []),
    updateDraft: vi.fn(async () => version),
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
        <AgentWorkbench versionId="version-id" />
      </SessionProvider>
    </LocaleProvider>,
  );
}

describe("Wave 1C real workbench locale boundary", () => {
  afterEach(() => {
    cleanup();
    navigation.push.mockReset();
  });

  it("does not publish unsaved local AGENT/avatar/voice state", async () => {
    const publish = vi.fn();
    const { api } = makeApi();
    api.publish = publish;
    renderWorkbench(api as unknown as PlatformApi, () => undefined);

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Publish version" }),
      ).toBeTruthy(),
    );
    const editor = screen.getByLabelText("AGENT.md editor");
    fireEvent.change(editor, { target: { value: "# Local Agent" } });

    const publishButton = screen.getByRole("button", {
      name: "Publish version",
    });
    expect((publishButton as HTMLButtonElement).disabled).toBe(true);
    expect(
      screen.getByText(
        /Save your local AGENT\.md, avatar, or voice changes before publishing\./,
      ),
    ).toBeTruthy();
    fireEvent.click(publishButton);
    expect(publish).not.toHaveBeenCalled();
  });

  it("writes the frozen English outline even when the interface is Chinese", async () => {
    const { api } = makeApi();
    renderWorkbench(api as unknown as PlatformApi, () => undefined);

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Switch to Chinese" }),
      ).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Switch to Chinese" }));
    fireEvent.click(screen.getByRole("button", { name: "插入参考大纲" }));

    expect(
      (screen.getByLabelText("AGENT.md 编辑器") as HTMLTextAreaElement).value,
    ).toBe(buildPersonaTemplate("Agent"));
    expect(
      (screen.getByLabelText("AGENT.md 编辑器") as HTMLTextAreaElement).value,
    ).toContain("# Identity");
    expect(
      (screen.getByLabelText("AGENT.md 编辑器") as HTMLTextAreaElement).value,
    ).not.toContain("# 身份");
  });

  it("preserves API/session/CSRF, selected docs, pending File, conflict, and retry identity across locale switches", async () => {
    const identities: IdentitySnapshot[] = [];
    const firstUploadFile = new File(["# pending"], "pending.md");
    const { api } = makeApi();
    api.uploadKnowledge
      .mockRejectedValueOnce(new TypeError("connection reset"))
      .mockResolvedValueOnce({
        agent_version: makeVersion({ revision: 2 }),
        document: makeDocument(),
      });
    renderWorkbench(api as unknown as PlatformApi, (value) => {
      identities.push(value);
    });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Publish version" }),
      ).toBeTruthy(),
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
      target: { value: "# Local while uploading" },
    });
    const uploadInput = screen.getByLabelText("Upload Markdown");
    fireEvent.change(uploadInput, { target: { files: [firstUploadFile] } });
    await waitFor(() =>
      expect(screen.getByText("connection reset")).toBeTruthy(),
    );
    const firstCall = api.uploadKnowledge.mock.calls[0];
    const firstHandle = (firstCall[4] as { idempotency: unknown }).idempotency;

    fireEvent.click(screen.getByRole("button", { name: "Switch to Chinese" }));
    const lastIdentity = identities.at(-1);
    expect(lastIdentity?.api).toBe(firstIdentity?.api);
    expect(lastIdentity?.session).toBe(firstIdentity?.session);
    expect(lastIdentity?.csrf).toBe(firstIdentity?.csrf);
    expect(
      (screen.getByLabelText("AGENT.md 编辑器") as HTMLTextAreaElement).value,
    ).toBe("# Local while uploading");
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(
      true,
    );
    expect(screen.getByText("evidence.md")).toBeTruthy();
    expect(screen.getByText(/# Evidence/)).toBeTruthy();
    expect(screen.getByText("Agent · V1.0")).toBeTruthy();
    expect(api.me.mock.calls.length).toBe(countsBefore.me);
    expect(api.version.mock.calls.length).toBe(countsBefore.version);
    expect(api.agent.mock.calls.length).toBe(countsBefore.agent);
    expect(api.knowledge.mock.calls.length).toBe(countsBefore.knowledge);
    expect(api.ragPreview.mock.calls.length).toBe(countsBefore.ragPreview + 1);
    expect(api.avatarTemplates.mock.calls.length).toBe(
      countsBefore.avatarTemplates,
    );
    expect(api.voiceProfiles.mock.calls.length).toBe(
      countsBefore.voiceProfiles,
    );

    fireEvent.click(screen.getByRole("button", { name: "切换到英文" }));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(api.uploadKnowledge).toHaveBeenCalledTimes(2));
    const secondCall = api.uploadKnowledge.mock.calls[1];
    expect(secondCall[2]).toBe(firstUploadFile);
    expect((secondCall[4] as { idempotency: unknown }).idempotency).toBe(
      firstHandle,
    );
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
      expect(
        screen.getByRole("button", { name: "Publish version" }),
      ).toBeTruthy(),
    );
    fireEvent.change(screen.getByLabelText("AGENT.md editor"), {
      target: { value: "# Conflict stays local" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
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
      "本地 AGENT.md 和证据选择仍保留",
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
  });
});
