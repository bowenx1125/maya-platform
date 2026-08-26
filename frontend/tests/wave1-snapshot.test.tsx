import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentDetail, AgentVersion, KnowledgeSnapshot } from "../lib/api";

vi.mock("../components/session-provider", () => ({
  useSession: vi.fn(),
}));

import { useSession } from "../components/session-provider";
import {
  canShowSnapshotText,
  TeacherAgentDetail,
} from "../components/teacher-workspace";
import { StudentPublishedVersion } from "../components/agent-workspace";

const mockedUseSession = vi.mocked(useSession);

function agent(): AgentDetail {
  return {
    id: "agent-id",
    group_id: "group-id",
    name: "Published Agent",
    description: "A released view",
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

  it("clears downloaded text when a teacher switches historical snapshots", async () => {
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
        Promise.resolve({
          ...snapshot(
            id === "11111111-1111-4111-8111-111111111111"
              ? "snapshot-one"
              : "snapshot-two",
          ),
          id,
        }),
      ),
      downloadSnapshot: vi.fn((id: string) => Promise.resolve(`# ${id}`)),
      downloadSnapshotDocument: vi.fn(),
    };
    mockedUseSession.mockReturnValue({ api } as never);

    const view = render(<TeacherAgentDetail agentId="agent-id" />);
    await waitFor(() => expect(screen.getByText("11111111…")).toBeTruthy());
    fireEvent.click(
      screen.getByRole("button", { name: "Download frozen RAG.md" }),
    );
    await waitFor(() =>
      expect(
        screen.getByText("# 11111111-1111-4111-8111-111111111111"),
      ).toBeTruthy(),
    );

    view.rerender(
      <TeacherAgentDetail
        agentId="agent-id"
        snapshotId="22222222-2222-4222-8222-222222222222"
      />,
    );
    await waitFor(() => expect(screen.getByText("22222222…")).toBeTruthy());
    expect(
      screen.queryByText("# 11111111-1111-4111-8111-111111111111"),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Download frozen RAG.md" }),
    );
    await waitFor(() =>
      expect(api.downloadSnapshot).toHaveBeenLastCalledWith(
        "22222222-2222-4222-8222-222222222222",
      ),
    );
    expect(canShowSnapshotText("snapshot-one", "snapshot-two")).toBe(false);
    expect(canShowSnapshotText("snapshot-two", "snapshot-two")).toBe(true);
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
      downloadSnapshot: vi.fn().mockResolvedValue("# frozen evidence"),
      downloadSnapshotDocument: vi.fn(),
    };
    mockedUseSession.mockReturnValue({ api } as never);

    render(<StudentPublishedVersion versionId="version-one" />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Download frozen RAG.md" }),
      ).toBeTruthy(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Download frozen RAG.md" }),
    );
    await waitFor(() =>
      expect(api.downloadSnapshot).toHaveBeenCalledWith(
        "11111111-1111-4111-8111-111111111111",
      ),
    );
    expect(screen.getByText("PUBLISHED SNAPSHOT")).toBeTruthy();
  });
});
