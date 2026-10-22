import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentWorkbench } from "../components/agent-workspace";
import { LocaleProvider } from "../components/locale";
import { useSession } from "../components/session-provider";
import type { AgentDetail, AgentVersion, KnowledgeDocument } from "../lib/api";
import { PlatformApiError } from "../lib/api";
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
    // The group library stays closed to a teacher who has not joined.
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
    <LocaleProvider initialLocale="en">
      <AgentWorkbench versionId="version-1" publishOnDone />
    </LocaleProvider>,
  );
  return api;
}

afterEach(() => {
  cleanup();
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
