import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentWorkbench } from "../components/agent-workspace";
import { AppShell } from "../components/app-shell";
import type { AvatarConfig } from "../components/avatar";
import { LocaleProvider } from "../components/locale";
import { SessionProvider } from "../components/session-provider";
import type {
  AgentDetail,
  AgentVersion,
  AuthSession,
  PlatformApi,
} from "../lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/student/agent-versions/version-id/edit",
}));

vi.mock("../components/avatar/avatar-renderer", () => ({
  AvatarRenderer: class {
    constructor(options: { onReady?: () => void }) {
      queueMicrotask(() => options.onReady?.());
    }

    setConfig(): void {
      return;
    }

    setState(): void {
      return;
    }

    dispose(): void {
      return;
    }
  },
}));

const initialAvatar: AvatarConfig = {
  template_id: "wave1-default-head",
  material_theme: "demo",
  eye_color: null,
  default_expression: "neutral",
  expression_strength: "medium",
  motion_style: "calm",
};

function makeVersion(overrides: Partial<AgentVersion> = {}): AgentVersion {
  return {
    id: "version-id",
    agent_id: "agent-id",
    version_label: "V1.0",
    state: "draft",
    revision: 0,
    agent_md: "# Server Agent",
    avatar_config: initialAvatar,
    voice_profile_id: null,
    effective_voice_profile_id: null,
    voice_fallback_active: true,
    knowledge_snapshot_id: null,
    enabled_documents: [],
    publish_blockers: [],
    ...overrides,
  } as AgentVersion;
}

function makeApi(version: AgentVersion) {
  const api = {
    me: vi.fn(async () => makeSession()),
    getCsrfToken: vi.fn(() => "csrf-1"),
    version: vi.fn(async () => version),
    agent: vi.fn(
      async () =>
        ({
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
        }) as AgentDetail,
    ),
    knowledge: vi.fn(async () => []),
    knowledgeSets: vi.fn(async () => []),
    agentKnowledgeSets: vi.fn(async () => ({
      agent_id: "agent-id",
      agent_metadata_revision: 0,
      sets: [],
    })),
    replaceAgentKnowledgeSets: vi.fn(
      async (
        _agentId: string,
        body: { expected_agent_metadata_revision: number },
      ) => ({
        agent_id: "agent-id",
        agent_metadata_revision: body.expected_agent_metadata_revision + 1,
        sets: [],
      }),
    ),
    ragPreview: vi.fn(async () => ({
      version_id: "version-id",
      total_char_count: 0,
      limit: null,
      document_count: 0,
      index_status: "ready",
      combined_markdown: "",
    })),
    avatarTemplates: vi.fn(async () => [
      {
        id: "wave1-default-head",
        name: "Wave 1 Default Head",
        available: true,
        supported_parameters: ["template_id", "material_theme", "eye_color"],
      },
      {
        id: "maya-warm-scholar",
        name: "Maya Warm Scholar",
        available: true,
        supported_parameters: ["template_id", "material_theme", "eye_color"],
      },
    ]),
    voiceProfiles: vi.fn(async () => []),
    updateDraft: vi.fn(
      async (_id: string, _body: { avatar_config?: AvatarConfig }) => version,
    ),
    publish: vi.fn(),
  };
  return api;
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

function renderWorkbench(api: PlatformApi) {
  return render(
    <LocaleProvider initialLocale="en">
      <SessionProvider api={api}>
        <AppShell role="student">
          <AgentWorkbench versionId="version-id" />
        </AppShell>
      </SessionProvider>
    </LocaleProvider>,
  );
}

describe("AvatarEditor draft persistence", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("saves appearance through UpdateAgentDraft and shows it after refresh", async () => {
    let stored = makeVersion();
    const api = makeApi(stored);
    api.updateDraft.mockImplementation(
      async (_id: string, body: { avatar_config?: AvatarConfig }) => {
        stored = makeVersion({
          revision: stored.revision + 1,
          avatar_config: body.avatar_config ?? stored.avatar_config,
        });
        return stored;
      },
    );
    api.publish.mockImplementation(async () => ({
      ...stored,
      state: "published",
    }));
    api.version.mockImplementation(async () => stored);

    const view = renderWorkbench(api as unknown as PlatformApi);
    const theme = await screen.findByLabelText("Material theme");
    expect((theme as HTMLSelectElement).value).toBe("demo");
    fireEvent.change(theme, { target: { value: "warm_sand" } });
    fireEvent.change(screen.getByLabelText("Eye color"), {
      target: { value: "blue" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledTimes(1));
    expect(api.updateDraft).toHaveBeenCalledWith(
      "version-id",
      expect.objectContaining({
        expected_revision: 0,
        avatar_config: {
          ...initialAvatar,
          material_theme: "warm_sand",
          eye_color: "blue",
        },
      }),
    );

    view.unmount();
    renderWorkbench(api as unknown as PlatformApi);
    const refreshed = await screen.findByLabelText("Material theme");
    expect((refreshed as HTMLSelectElement).value).toBe("warm_sand");
    expect(
      (screen.getByLabelText("Eye color") as HTMLSelectElement).value,
    ).toBe("blue");
  });

  it("renders a load failure before constructing the Agent Knowledge link", async () => {
    const api = makeApi(makeVersion());
    api.version.mockRejectedValue(new Error("Draft unavailable"));

    renderWorkbench(api as unknown as PlatformApi);

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});
