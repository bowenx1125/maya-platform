import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentDetail, AgentVersion, KnowledgeSnapshot } from "../lib/api";

vi.mock("../components/session-provider", () => ({
  useSession: vi.fn(),
}));

import { useSession } from "../components/session-provider";
import { TeacherAgentDetail } from "../components/teacher-workspace";
import { StudentPublishedVersion } from "../components/agent-workspace";

const mockedUseSession = vi.mocked(useSession);

function agent(): AgentDetail {
  return {
    id: "agent-id",
    group_id: "group-id",
    course_id: "course-id",
    ownership_scope: "group",
    visibility: "public",
    can_edit: false,
    name: "Published Agent",
    description: "A released view",
    metadata_revision: 0,
    status: "active",
    current_published_version_id: "version-one",
    current_draft_version_id: null,
    versions: [],
  };
}

function version(
  id: string,
  snapshotId: string,
  state: AgentVersion["state"],
): AgentVersion {
  return {
    id,
    agent_id: "agent-id",
    version_label: id === "version-one" ? "V1.0" : "V1.1",
    state,
    revision: 1,
    agent_md: `# ${id}`,
    avatar_config: {
      template_id: "wave1-default-head",
      material_theme: "indigo",
      default_expression: "neutral",
      expression_strength: "medium",
      motion_style: "calm",
    },
    voice_fallback_active: true,
    persona_confirmed: false,
    knowledge_snapshot_id: snapshotId,
    enabled_documents: [],
    publish_blockers: [],
  } as AgentVersion;
}

function snapshot(id: string): KnowledgeSnapshot {
  return {
    id,
    agent_version_id: id === "snapshot-one" ? "version-one" : "version-two",
    content_hash: `hash-${id}`,
    total_char_count: 22,
    documents: [],
    created_at: "2026-08-27T00:00:00Z",
  } as KnowledgeSnapshot;
}

describe("student and teacher snapshot selection", () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      () => undefined,
    );
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:maya"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("checks one attached file without downloading the rest", async () => {
    const published = version(
      "version-one",
      "11111111-1111-4111-8111-111111111111",
      "published",
    );
    published.enabled_documents = [
      {
        id: "one",
        source_filename: "One.md",
        char_count: 20,
      },
      {
        id: "two",
        source_filename: "Two.md",
        char_count: 20,
      },
    ] as AgentVersion["enabled_documents"];
    const api = {
      agent: vi.fn().mockResolvedValue(agent()),
      versions: vi.fn().mockResolvedValue([published]),
      snapshot: vi.fn(),
      downloadKnowledge: vi.fn((id: string) =>
        Promise.resolve({ content: `# ${id}`, filename: `${id}.md` }),
      ),
      downloadSnapshot: vi.fn(),
      downloadSnapshotDocument: vi.fn(),
    };
    mockedUseSession.mockReturnValue({ api } as never);
    render(<TeacherAgentDetail agentId="agent-id" />);
    await screen.findByRole("heading", { name: "version-one" });
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Done" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "View One.md" }));
    const dialog = await screen.findByRole("dialog", { name: "One.md" });
    expect(within(dialog).getByRole("heading", { name: "one" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "two" })).toBeNull();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Download Two.md" }));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
    expect(api.downloadKnowledge).toHaveBeenLastCalledWith("two", "Two.md");
    expect(api.downloadSnapshot).not.toHaveBeenCalled();
  });

  it("marks the displayed teacher snapshot and keeps other versions navigable", async () => {
    const api = {
      agent: vi.fn().mockResolvedValue(agent()),
      versions: vi
        .fn()
        .mockResolvedValue([
          version(
            "version-one",
            "11111111-1111-4111-8111-111111111111",
            "published",
          ),
          version(
            "version-two",
            "22222222-2222-4222-8222-222222222222",
            "superseded",
          ),
        ]),
      snapshot: vi.fn((id: string) =>
        Promise.resolve({ ...snapshot("snapshot-one"), id }),
      ),
      downloadSnapshot: vi.fn(),
      downloadSnapshotDocument: vi.fn(),
    };
    mockedUseSession.mockReturnValue({ api } as never);

    render(<TeacherAgentDetail agentId="agent-id" />);
    expect(
      await screen.findByRole("heading", { name: "version-one" }),
    ).toBeTruthy();
    expect(screen.queryByRole("link", { name: "V1.0 Published" })).toBeNull();
    expect(screen.queryByRole("link", { name: "V1.1 Previous" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Versions" })).toBeNull();
    expect(screen.queryByText("Viewing")).toBeNull();
  });

  it("lets a same-group student inspect and download a published snapshot", async () => {
    const published = version(
      "version-one",
      "11111111-1111-4111-8111-111111111111",
      "published",
    );
    const api = {
      version: vi.fn().mockResolvedValue(published),
      agent: vi.fn().mockResolvedValue(agent()),
      snapshot: vi.fn().mockResolvedValue({
        ...snapshot("snapshot-one"),
        id: "11111111-1111-4111-8111-111111111111",
      }),
      downloadSnapshot: vi.fn().mockResolvedValue({
        content: "# frozen evidence",
        filename: "RAG--Agent--V1.0.md",
      }),
      downloadSnapshotDocument: vi.fn(),
    };
    mockedUseSession.mockReturnValue({ api } as never);

    render(<StudentPublishedVersion versionId="version-one" />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Download RAG" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Download RAG" }));
    await waitFor(() =>
      expect(api.downloadSnapshot).toHaveBeenCalledWith(
        "11111111-1111-4111-8111-111111111111",
      ),
    );
    expect(screen.queryByText("Version")).toBeNull();
    expect(
      screen.getByRole("heading", { level: 1, name: "Published Agent · V1.0" })
        .className,
    ).toBe("sr-only");
  });
});
