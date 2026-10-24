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
import type { ComponentProps } from "react";

import { AgentWorkbench } from "../components/agent-workspace";
import { AppShell } from "../components/app-shell";
import type { AvatarConfig } from "../components/avatar";
import { LocaleProvider } from "../components/locale";
import { SessionProvider } from "../components/session-provider";
import { PlatformApiError } from "../lib/api";
import type {
  AgentDetail,
  AgentVersion,
  AuthSession,
  PlatformApi,
  VoiceProfile,
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
    voiceProfiles: vi.fn(async (): Promise<VoiceProfile[]> => []),
    personalVoiceProfiles: vi.fn(async (): Promise<VoiceProfile[]> => []),
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

function renderWorkbench(
  api: PlatformApi,
  publishOnDone = false,
  unsavedCreate?: ComponentProps<typeof AgentWorkbench>["unsavedCreate"],
) {
  return render(
    <LocaleProvider initialLocale="en">
      <SessionProvider api={api}>
        <AppShell role="student">
          <AgentWorkbench
            versionId={unsavedCreate ? undefined : "version-id"}
            publishOnDone={publishOnDone}
            unsavedCreate={unsavedCreate}
          />
        </AppShell>
      </SessionProvider>
    </LocaleProvider>,
  );
}

describe("Agent hint bar", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("names no RAG, Voice None and a non-standard AGENT.md, and closes", async () => {
    const version = makeVersion({ agent_md: "only text, no heading" });
    renderWorkbench(makeApi(version) as unknown as PlatformApi, true);
    const bar = await screen.findByRole("note");
    expect(bar.textContent).toContain("This Agent is not ready for a Debate:");
    expect(bar.textContent).toContain(
      "Agent “Agent” needs at least one RAG file.",
    );
    expect(bar.textContent).toContain(
      "Agent “Agent” has no Voice (Voice is None).",
    );
    expect(bar.textContent).toContain(
      "Agent “Agent” has a non-standard AGENT.md: it needs a heading line starting with # and some text under it.",
    );
    fireEvent.click(within(bar).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("stays away when the Agent has RAG, a Voice and a standard AGENT.md", async () => {
    const version = makeVersion({
      agent_md: "# Agent\n\nA clear perspective.",
      voice_profile_id: "voice-1",
      enabled_documents: [
        {
          id: "doc-1",
          source_filename: "notes.md",
          workspace_state: "active",
          index_status: "ready",
          index_revision: 1,
          char_count: 10,
          content_hash: "a".repeat(64),
          authorization_epoch: 0,
          can_manage_visibility: true,
          course_id: "course-id",
          group_id: "group-id",
          ownership_scope: "group",
          visibility: "public",
          created_at: "2026-01-01T00:00:00Z",
        },
      ] as unknown as AgentVersion["enabled_documents"],
    });
    renderWorkbench(makeApi(version) as unknown as PlatformApi, true);
    await screen.findByLabelText("Material theme");
    expect(screen.queryByRole("note")).toBeNull();
  });
});
