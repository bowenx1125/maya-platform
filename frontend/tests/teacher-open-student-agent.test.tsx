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
import { useSession } from "../components/session-provider";
import type { AgentDetail, AgentVersion, KnowledgeDocument } from "../lib/api";
import { PlatformApiError } from "../lib/api";
import {
  agentDraftStashKey,
  loadAgentDraftStash,
} from "../lib/agent-draft-stash";
import { groupLibraryOrClosed } from "../lib/group-library";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/teacher/agents/agent-1",
}));
vi.mock("../components/session-provider", () => ({ useSession: vi.fn() }));
vi.mock("../components/avatar/avatar-canvas", () => ({
  AvatarCanvas: () => <div role="img" aria-label="Agent avatar" />,
}));

// A student's public source, already bound to the published version.
const bound: KnowledgeDocument = {
  id: "source-1",
  course_id: "course-1",
  group_id: "group-1",
  ownership_scope: "group",
  visibility: "public",
  can_manage_visibility: false,
  authorization_epoch: 0,
  source_filename: "student-notes.md",
  char_count: 40,
  workspace_state: "active",
  index_status: "ready",
} as KnowledgeDocument;

const published = {
  id: "version-1",
  agent_id: "agent-1",
  version_label: "V1.0",
  state: "published",
  revision: 0,
  agent_md: "# Student public Agent",
  avatar_config: null,
  voice_profile_id: null,
  effective_voice_profile_id: null,
  voice_fallback_active: true,
  knowledge_snapshot_id: null,
  enabled_documents: [bound],
  publish_blockers: [],
} as unknown as AgentVersion;

// PR #229: a course teacher may edit a student's public Agent (can_edit),
// without being a member of the student's group.
const agent = {
  id: "agent-1",
  group_id: "group-1",
  course_id: "course-1",
  ownership_scope: "group",
  visibility: "public",
  can_edit: true,
  can_delete: true,
  is_creator: false,
  name: "Student public Agent",
  description: "",
  metadata_revision: 0,
  status: "active",
  current_draft_version_id: null,
  current_published_version_id: "version-1",
  versions: [],
} as unknown as AgentDetail;

const notFound = () =>
  new PlatformApiError(404, "Not found", {
    code: "not_found",
    message: "Not found",
  } as never);

function renderAsCourseTeacher() {
  const api = {
    personalVoiceProfiles: vi.fn(async () => []),
    version: vi.fn(async () => published),
    agent: vi.fn(async () => agent),
    versions: vi.fn(async () => [published]),
    // A teacher who has not entered the group still gets 404. Entering would
    // return the member library; this fallback only covers the closed case.
    knowledge: vi.fn(async () => {
      throw notFound();
    }),
    knowledgeSets: vi.fn(async () => []),
    agentKnowledgeSets: vi.fn(async () => ({
      agent_id: "agent-1",
      agent_metadata_revision: 0,
      sets: [],
    })),
    ragPreview: vi.fn(async () => null),
    avatarTemplates: vi.fn(async () => []),
  };
  vi.mocked(useSession).mockReturnValue({
    api,
    user: {
      id: "teacher-1",
      courses: [{ course_id: "course-1", role: "teacher" }],
      groups: [],
    },
    logout: vi.fn(),
  } as never);
  render(
    <>
      <AgentWorkbench versionId="version-1" publishOnDone />
    </>,
  );
  return api;
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.mocked(useSession).mockReset();
  vi.restoreAllMocks();
});

describe("course teacher opens a student's public Agent", () => {
  it("loads the editor instead of 'Agent deleted or no longer shared'", async () => {
    const api = renderAsCourseTeacher();
    expect(
      await screen.findByRole("textbox", { name: "AGENT.md editor" }),
    ).toBeTruthy();
    expect(api.knowledge).toHaveBeenCalledWith("group-1");
    expect(
      screen.queryByText(
        "This Agent was deleted or is no longer shared with you.",
      ),
    ).toBeNull();
    // The bound public source stays visible and selected.
    expect(screen.getByText(/student-notes\.md/)).toBeTruthy();
  });
});

describe("groupLibraryOrClosed", () => {
  it("treats a closed group library as empty", async () => {
    await expect(
      groupLibraryOrClosed(Promise.reject(notFound())),
    ).resolves.toEqual([]);
  });

  it("still surfaces every other failure", async () => {
    const denied = new PlatformApiError(500, "boom");
    await expect(groupLibraryOrClosed(Promise.reject(denied))).rejects.toBe(
      denied,
    );
  });
});

describe("concurrent Done on a shared public Agent", () => {
  const v11 = {
    ...published,
    id: "version-2",
    version_label: "V1.1",
    agent_md: "# Student public Agent\nteacher won",
  } as unknown as AgentVersion;

  function renderEditor(
    base: AgentVersion,
    nextVersion: (...args: unknown[]) => Promise<AgentVersion>,
  ) {
    const draft = {
      ...base,
      id: "draft-1",
      state: "draft",
      revision: 0,
    } as unknown as AgentVersion;
    const api = {
      personalVoiceProfiles: vi.fn(async () => []),
      version: vi.fn(async () => base),
      agent: vi.fn(async () => ({
        ...agent,
        current_published_version_id: base.id,
      })),
      versions: vi.fn(async () => [base]),
      knowledge: vi.fn(async () => [bound]),
      knowledgeSets: vi.fn(async () => []),
      agentKnowledgeSets: vi.fn(async () => ({
        agent_id: "agent-1",
        agent_metadata_revision: 0,
        sets: [],
      })),
      ragPreview: vi.fn(async () => null),
      avatarTemplates: vi.fn(async () => []),
      nextVersion: vi.fn(nextVersion),
      updateDraft: vi.fn(
        async (_id: string, body: { agent_md?: string }) =>
          ({
            ...draft,
            revision: 1,
            agent_md: body.agent_md,
          }) as unknown as AgentVersion,
      ),
      setDocuments: vi.fn(async () => ({ ...draft, revision: 2 })),
      publish: vi.fn(async () => ({
        ...draft,
        id: "draft-1",
        state: "published",
        version_label: "V1.2",
      })),
    };
    vi.mocked(useSession).mockReturnValue({
      api,
      user: {
        id: "kaikai-1",
        courses: [{ course_id: "course-1", role: "student" }],
        groups: [],
      },
      logout: vi.fn(),
    } as never);
    render(
      <>
        <AppShell role="student">
          <AgentWorkbench
            versionId={base.id}
            publishOnDone
            backHref="/student/groups/group-1"
          />
        </AppShell>
      </>,
    );
    return { api, draft };
  }

  it("rejects the second Done, keeps the draft locally and restores it after refresh", async () => {
    const stale = new PlatformApiError(409, "stale", {
      code: "stale_base_version",
      message: "Someone else published a newer version of this Agent.",
      details: {
        expected_base_version_id: "version-1",
        current_published_version_id: "version-2",
        current_version_label: "V1.1",
      },
    } as never);
    const first = renderEditor(published, async () => {
      throw stale;
    });
    const editor = await screen.findByRole("textbox", {
      name: "AGENT.md editor",
    });
    fireEvent.change(editor, {
      target: { value: "# Student public Agent\ngroupmate edit" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    // Rejected with the base the editor started from, told to refresh.
    await screen.findByText("Revision conflict");
    expect(first.api.nextVersion).toHaveBeenCalledWith(
      "agent-1",
      expect.objectContaining({ expectedBaseVersionId: "version-1" }),
    );
    expect(first.api.publish).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeTruthy();
    expect(
      screen.getByText(/your edits are kept in this browser/),
    ).toBeTruthy();
    const stash = loadAgentDraftStash("kaikai-1", "agent-1");
    expect(stash?.agent_md).toBe("# Student public Agent\ngroupmate edit");
    expect(stash?.base_version_id).toBe("version-1");
    expect(
      window.localStorage.getItem(
        agentDraftStashKey("someone-else", "agent-1"),
      ),
    ).toBeNull();

    // "Refresh": the editor now opens the latest version (V1.1) and the
    // local draft goes straight back into the fields.
    cleanup();
    const second = renderEditor(v11, async () => second.draft);
    const restored = (await screen.findByRole("textbox", {
      name: "AGENT.md editor",
    })) as HTMLTextAreaElement;
    expect(restored.value).toBe("# Student public Agent\ngroupmate edit");
    expect(screen.getByText(/unpublished edits were restored/)).toBeTruthy();

    // Done now succeeds from the new base and clears the local draft.
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(second.api.publish).toHaveBeenCalled());
    expect(second.api.nextVersion).toHaveBeenCalledWith(
      "agent-1",
      expect.objectContaining({ expectedBaseVersionId: "version-2" }),
    );
    expect(second.api.updateDraft).toHaveBeenCalledWith(
      "draft-1",
      expect.objectContaining({
        agent_md: "# Student public Agent\ngroupmate edit",
      }),
    );
    await waitFor(() =>
      expect(loadAgentDraftStash("kaikai-1", "agent-1")).toBeNull(),
    );
  });
});
