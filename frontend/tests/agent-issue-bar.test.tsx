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

type Issue = { issue: string; blocking?: boolean };

function readiness(issues: Issue[]) {
  const messages: Record<string, string> = {
    rag_missing: "needs RAG",
    voice_missing: "voice none",
    agent_md_invalid: "agent md",
    avatar_missing: "avatar",
  };
  return issues.map((item) => ({
    agent_id: "agent-id",
    agent_name: "Agent",
    issue: item.issue,
    blocking: item.blocking ?? item.issue !== "voice_missing",
    message: messages[item.issue] ?? item.issue,
  }));
}

function makeApi(version: AgentVersion, issues: Issue[][] = [[]]) {
  let read = 0;
  const api = {
    me: vi.fn(async () => makeSession()),
    getCsrfToken: vi.fn(() => "csrf-1"),
    version: vi.fn(async () => version),
    agent: vi.fn(
      async () =>
        ({
          readiness_issues: readiness(
            issues[Math.min(read++, issues.length - 1)],
          ),
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
    publish: vi.fn(async () => ({ ...version, state: "published" })),
    nextVersion: vi.fn(async () => ({ ...version, state: "draft" })),
    versions: vi.fn(async () => [version]),
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

function editAgentMd(value: string) {
  fireEvent.change(screen.getByLabelText(/AGENT\.md.*editor/i), {
    target: { value },
  });
}

describe("Agent hint bar", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  const all = [
    { issue: "rag_missing" },
    { issue: "voice_missing" },
    { issue: "agent_md_invalid" },
    { issue: "avatar_missing" },
  ];

  it("lists the server's checks of the published version at the top, and closes", async () => {
    const { container } = renderWorkbench(
      makeApi(makeVersion(), [all]) as unknown as PlatformApi,
      true,
    );
    const bar = await screen.findByRole("note");
    expect(bar.className).toBe("agent-hint-bar");
    expect(bar.textContent).toContain("This Agent is not ready for a Debate:");
    expect(bar.textContent).toContain(
      "Agent “Agent” needs at least one RAG file.",
    );
    expect(bar.textContent).toContain("Agent “Agent” has no Voice");
    expect(bar.textContent).toContain(
      "Agent “Agent” has a non-standard AGENT.md",
    );
    expect(bar.textContent).toContain("Agent “Agent” has no usable Avatar.");
    // Above the editor: the first block after the page title.
    const heading = container.querySelector("h1");
    expect(
      heading &&
        heading.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const form = container.querySelector("textarea");
    expect(
      form &&
        bar.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.click(within(bar).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("stays away when the published version passes every check", async () => {
    renderWorkbench(
      makeApi(makeVersion(), [[]]) as unknown as PlatformApi,
      true,
    );
    await screen.findByLabelText("Material theme");
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("each line's Done publishes and removes only that line once it passes", async () => {
    // Load, then after the RAG line's Done: RAG and Voice pass on the server.
    const api = makeApi(makeVersion(), [
      all,
      [{ issue: "agent_md_invalid" }, { issue: "avatar_missing" }],
      [{ issue: "avatar_missing" }],
    ]);
    renderWorkbench(api as unknown as PlatformApi, true);
    const bar = await screen.findByRole("note");
    const checks = within(bar).getAllByRole("button", {
      name: "Done: save, publish and check this again",
    });
    expect(checks).toHaveLength(4);
    editAgentMd("# Agent\n\nA clear perspective.");
    fireEvent.click(checks[0]);
    await waitFor(() => expect(api.publish).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(bar.textContent).not.toContain("needs at least one RAG file"),
    );
    // Voice also passes now, but only the checked line moves.
    expect(bar.textContent).toContain("has no Voice");
    expect(bar.textContent).toContain("non-standard AGENT.md");

    // A line that still fails stays after its Done.
    editAgentMd("# Agent\n\nA clearer perspective.");
    const avatarCheck = within(bar)
      .getAllByRole("listitem")
      .find((item) => item.getAttribute("data-issue") === "avatar_missing")!;
    fireEvent.click(
      within(avatarCheck).getByRole("button", {
        name: "Done: save, publish and check this again",
      }),
    );
    await waitFor(() => expect(api.publish).toHaveBeenCalledTimes(2));
    await act(async () => undefined);
    expect(bar.textContent).toContain("has no usable Avatar.");
  });

  it("publishes an Agent that still has open hints: they never block saving", async () => {
    const api = makeApi(makeVersion(), [all]);
    renderWorkbench(api as unknown as PlatformApi, true);
    await screen.findByRole("note");
    editAgentMd("still no heading");
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));
    await waitFor(() => expect(api.publish).toHaveBeenCalled());
  });
});
