import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentWorkbench } from "../components/agent-workspace";
import { useSession } from "../components/session-provider";
import type { AgentDetail, AgentVersion, KnowledgeDocument } from "../lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/teacher/agents/agent-1",
}));
vi.mock("../components/session-provider", () => ({ useSession: vi.fn() }));
vi.mock("../components/avatar/avatar-canvas", () => ({
  AvatarCanvas: () => <div role="img" aria-label="Agent avatar" />,
}));

function source(
  id: string,
  name: string,
  overrides: Partial<KnowledgeDocument> = {},
): KnowledgeDocument {
  return {
    id,
    course_id: "course-1",
    group_id: "group-1",
    ownership_scope: "group",
    visibility: "public",
    can_manage_visibility: false,
    authorization_epoch: 0,
    source_filename: name,
    char_count: 40,
    workspace_state: "active",
    index_status: "ready",
    ...overrides,
  } as KnowledgeDocument;
}

const bound = source("source-1", "Notes.md");
const removed = source("source-2", "Removed.md", { workspace_state: "hidden" });

const published = {
  id: "version-1",
  agent_id: "agent-1",
  version_label: "V1.0",
  state: "published",
  revision: 0,
  agent_md: "# Public Agent",
  avatar_config: null,
  voice_profile_id: null,
  effective_voice_profile_id: null,
  voice_fallback_active: true,
  knowledge_snapshot_id: null,
  enabled_documents: [bound, removed],
  publish_blockers: [],
} as unknown as AgentVersion;

const agent = {
  id: "agent-1",
  group_id: "group-1",
  course_id: "course-1",
  ownership_scope: "group",
  visibility: "public",
  can_edit: true,
  can_delete: true,
  is_creator: true,
  name: "Public Agent",
  description: "",
  metadata_revision: 0,
  status: "active",
  current_draft_version_id: null,
  current_published_version_id: "version-1",
  versions: [],
} as unknown as AgentDetail;

const unitSet = {
  id: "set-1",
  course_id: "course-1",
  display_name: "Unit Knowledge",
  can_edit: true,
};

function renderWorkbench() {
  const api = {
    version: vi.fn(async () => published),
    agent: vi.fn(async () => agent),
    versions: vi.fn(async () => [published]),
    knowledge: vi.fn(async () => [bound]),
    knowledgeSets: vi.fn(async () => [unitSet]),
    agentKnowledgeSets: vi.fn(async () => ({
      agent_id: "agent-1",
      agent_metadata_revision: 0,
      sets: [unitSet],
    })),
    ragPreview: vi.fn(async () => null),
    avatarTemplates: vi.fn(async () => []),
    voiceProfiles: vi.fn(async () => []),
    downloadKnowledge: vi.fn(async (id: string, filename: string) => ({
      content: `# Server copy of ${id}`,
      filename,
    })),
    knowledgeMarkdown: vi.fn(async (setId: string) => ({
      markdown: `# Saved ${setId}`,
    })),
  };
  vi.mocked(useSession).mockReturnValue({
    api,
    user: {
      id: "student-1",
      courses: [{ course_id: "course-1", role: "student" }],
      groups: [{ group_id: "group-1" }],
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

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:brainform");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.mocked(useSession).mockReset();
  vi.restoreAllMocks();
});

describe("edit-mode Brainform view and download", () => {
  it("opens the server copy of a RAG file in the check overlay without toggling it", async () => {
    const api = renderWorkbench();
    const view = await screen.findByRole("button", { name: "View Notes.md" });
    const checkbox = screen.getByRole("checkbox", {
      name: "Notes.md",
    }) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    // The buttons sit outside the selection label.
    expect(view.closest("label")).toBeNull();

    fireEvent.click(view);
    const dialog = await screen.findByRole("dialog", { name: "Notes.md" });
    expect(
      within(dialog).getByRole("heading", {
        name: "Server copy of source-1",
      }),
    ).toBeTruthy();
    expect(api.downloadKnowledge).toHaveBeenCalledWith("source-1", "Notes.md");
    expect(document.querySelector(".knowledge-check")).toBeTruthy();
    expect(checkbox.checked).toBe(true);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(checkbox.checked).toBe(true);
    // Viewing is read-only: it never saves the draft.
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("downloads RAG without toggling it and has no Knowledge Set actions", async () => {
    const api = renderWorkbench();
    fireEvent.click(
      await screen.findByRole("button", { name: "Download Notes.md" }),
    );
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
    expect(api.downloadKnowledge).toHaveBeenLastCalledWith(
      "source-1",
      "Notes.md",
    );

    expect(screen.getByRole("checkbox", { name: "Notes.md" })).toHaveProperty(
      "checked",
      true,
    );
    expect(
      screen
        .getByRole("button", { name: "Download Notes.md" })
        .closest("label"),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "View Unit Knowledge" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Download Unit Knowledge" }),
    ).toBeNull();
    expect(
      screen.queryByRole("checkbox", { name: "Unit Knowledge" }),
    ).toBeNull();
    expect(api.knowledgeMarkdown).not.toHaveBeenCalled();
  });

  it("disables view and download for a file removed from the library", async () => {
    const api = renderWorkbench();
    const view = await screen.findByRole("button", {
      name: "View Removed.md",
    });
    const download = screen.getByRole("button", {
      name: "Download Removed.md",
    });
    expect((view as HTMLButtonElement).disabled).toBe(true);
    expect((download as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(view);
    expect(api.downloadKnowledge).not.toHaveBeenCalled();
  });
});
