import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentDetail, AgentVersion, KnowledgeSnapshot } from "../lib/api";
import { t } from "../lib/i18n";

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
      downloadSnapshot: vi.fn((id: string) =>
        Promise.resolve({
          content: `# ${id}`,
          filename: `RAG--Agent--V1.0.md`,
        }),
      ),
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

    const view = render(<TeacherAgentDetail agentId="agent-id" />);
    await waitFor(() => expect(screen.getAllByText("Viewing")).toHaveLength(2));
    expect(t("viewingSnapshot", "en")).toBe("Viewing");
    expect(t("viewingSnapshot", "zh")).toBe("正在查看");
    const viewingIndicators = screen.getAllByText("Viewing");
    expect(
      viewingIndicators.every(
        (item) =>
          item.getAttribute("aria-current") === "page" &&
          item.classList.contains("current-version-indicator") &&
          item.closest("a") === null &&
          item.getAttribute("href") === null,
      ),
    ).toBe(true);
    expect(screen.queryAllByRole("link", { name: "Viewing" })).toHaveLength(0);
    const initialInspectLinks = screen.getAllByRole("link", {
      name: "Inspect →",
    });
    expect(initialInspectLinks).toHaveLength(1);
    expect(initialInspectLinks[0]?.getAttribute("href")).toBe(
      "/teacher/agents/agent-id?snapshot=22222222-2222-4222-8222-222222222222",
    );

    view.rerender(
      <TeacherAgentDetail
        agentId="agent-id"
        snapshotId="22222222-2222-4222-8222-222222222222"
      />,
    );
    await waitFor(() => expect(screen.getAllByText("Viewing")).toHaveLength(1));
    const historicalInspectLinks = screen.getAllByRole("link", {
      name: "Inspect →",
    });
    expect(historicalInspectLinks).toHaveLength(2);
    expect(
      historicalInspectLinks.map((link) => link.getAttribute("href")),
    ).toEqual([
      "/teacher/agents/agent-id?snapshot=11111111-1111-4111-8111-111111111111",
      "/teacher/agents/agent-id?snapshot=11111111-1111-4111-8111-111111111111",
    ]);
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
