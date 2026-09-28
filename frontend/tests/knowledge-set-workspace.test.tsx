import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { KnowledgeSetWorkspace } from "../components/knowledge/knowledge-set-workspace";
import { LocaleProvider } from "../components/locale";
import { useSession } from "../components/session-provider";
import type {
  AgentKnowledgeSets,
  KnowledgeAsset,
  KnowledgeAssetFull,
  KnowledgeGraph,
  KnowledgeSetDetail,
  KnowledgeSetSummary,
} from "../lib/api";

vi.mock("../components/session-provider", () => ({
  useSession: vi.fn(),
}));

const mockedUseSession = vi.mocked(useSession);
const courseId = "course-1";
const teacherId = "teacher-1";
const setId = "set-1";
const bindingId = "binding-1";
const assetId = "question-1";
const conceptId = "concept-1";
const hash = "a".repeat(64);

function setSummary(
  overrides: Partial<KnowledgeSetSummary> = {},
): KnowledgeSetSummary {
  return {
    id: setId,
    owner_user_id: teacherId,
    course_id: courseId,
    group_id: null,
    ownership_scope: "personal",
    visibility: "private",
    display_name: "Set Alpha",
    metadata_revision: 0,
    content_revision: 3,
    authorization_epoch: 0,
    source_count: 1,
    asset_count: 2,
    can_edit: true,
    created_at: "2026-09-27T12:00:00Z",
    updated_at: "2026-09-27T12:00:00Z",
    ...overrides,
  };
}

function setDetail(): KnowledgeSetDetail {
  return {
    ...setSummary(),
    sources: [
      {
        id: bindingId,
        document_id: "document-1",
        source_filename: "lesson.md",
        char_count: 240,
        content_hash: hash,
        authorization_epoch: 0,
        order_index: 0,
        is_active: true,
        available: true,
      },
    ],
  };
}

function conceptAsset(): KnowledgeAssetFull {
  return {
    audience: "full",
    id: conceptId,
    knowledge_set_id: setId,
    kind: "concept",
    current_version_seq: 1,
    current_version: {
      id: "concept-version-1",
      asset_id: conceptId,
      version_seq: 1,
      content: {
        kind: "concept",
        title: "Evaporation",
        description: "Liquid becomes vapor.",
        prerequisite_ids: [],
        citations: [],
      },
      content_hash: hash,
      created_by_user_id: teacherId,
      created_at: "2026-09-27T12:00:00Z",
    },
    can_edit: true,
    created_at: "2026-09-27T12:00:00Z",
    updated_at: "2026-09-27T12:00:00Z",
  } as KnowledgeAssetFull;
}

function questionAsset(): KnowledgeAssetFull {
  return {
    audience: "full",
    id: assetId,
    knowledge_set_id: setId,
    kind: "question",
    current_version_seq: 2,
    current_version: {
      id: "question-version-2",
      asset_id: assetId,
      version_seq: 2,
      content: {
        kind: "question",
        prompt: "Explain evaporation.",
        reference_answer: "Teacher answer canary.",
        concept_ids: [conceptId],
        citations: [
          {
            source_binding_id: bindingId,
            location: {
              section_path: ["Water cycle", "Evaporation"],
              start_offset: 19,
              end_offset: 42,
              paragraph_index: 3,
              excerpt_hash: hash,
            },
          },
        ],
        rubric: {
          criteria: [
            { label: "Cause", guidance: "Names the heat source.", points: 2 },
            { label: "Change", guidance: "Explains vaporization.", points: 3 },
          ],
          total_points: 5,
        },
      },
      content_hash: hash,
      created_by_user_id: teacherId,
      created_at: "2026-09-27T12:00:00Z",
    },
    can_edit: true,
    created_at: "2026-09-27T12:00:00Z",
    updated_at: "2026-09-27T12:00:00Z",
  } as KnowledgeAssetFull;
}

function graph(): KnowledgeGraph {
  return {
    set_id: setId,
    content_revision: 3,
    nodes: [
      {
        id: conceptId,
        title: "Evaporation",
        description: "Liquid becomes vapor.",
      },
    ],
    edges: [],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve: (value: T) => resolve(value) };
}

function mockApi(overrides: Record<string, unknown> = {}) {
  const set = setSummary();
  const detail = setDetail();
  return {
    courses: vi
      .fn()
      .mockResolvedValue([
        { id: courseId, code: "COURSE-1", name: "Course One" },
      ]),
    knowledgeSets: vi.fn().mockResolvedValue([set]),
    knowledgeGenerationJob: vi.fn().mockResolvedValue({
      job_id: "job-1",
      run_id: "run-1",
      knowledge_set_id: setId,
      state: "pending",
      created_at: "2026-09-27T12:00:00Z",
      updated_at: "2026-09-27T12:00:00Z",
      safe_error_code: null,
      accepted_item_count: 0,
      materialized_item_count: 0,
      failed_item_count: 0,
    }),
    groups: vi.fn().mockResolvedValue([]),
    workspaceAgents: vi.fn().mockResolvedValue([]),
    knowledgeSet: vi.fn().mockResolvedValue(detail),
    knowledgeSetAssets: vi
      .fn()
      .mockResolvedValue([conceptAsset(), questionAsset()]),
    knowledgeSetGraph: vi.fn().mockResolvedValue(graph()),
    knowledgeSetAssetVersions: vi.fn().mockResolvedValue({
      audience: "full",
      asset_id: questionAsset().id,
      versions: [questionAsset().current_version],
    }),
    workspaceDocuments: vi.fn().mockResolvedValue([]),
    knowledge: vi.fn().mockResolvedValue([]),
    updateKnowledgeSet: vi
      .fn()
      .mockResolvedValue({ ...detail, display_name: "Set Beta" }),
    createKnowledgeSet: vi.fn().mockResolvedValue(detail),
    updateKnowledgeSetAsset: vi.fn().mockResolvedValue(questionAsset()),
    createKnowledgeSetAsset: vi.fn().mockResolvedValue(questionAsset()),
    knowledgeSetAsset: vi.fn().mockResolvedValue(conceptAsset()),
    agent: vi.fn().mockResolvedValue({ id: "agent-1", course_id: courseId }),
    agentKnowledgeSets: vi.fn().mockResolvedValue({
      agent_id: "agent-1",
      agent_metadata_revision: 0,
      sets: [set],
    } satisfies AgentKnowledgeSets),
    replaceAgentKnowledgeSets: vi.fn().mockResolvedValue({
      agent_id: "agent-1",
      agent_metadata_revision: 1,
      sets: [],
    }),
    ...overrides,
  };
}

function renderWorkspace(
  api: ReturnType<typeof mockApi>,
  agentId?: string,
  courses = [{ course_id: courseId, role: "teacher" }],
  role: "teacher" | "student" = "teacher",
  groups: Array<{ group_id: string; role: string }> = [],
  generation?: { jobId: string; setId?: string },
) {
  mockedUseSession.mockReturnValue({
    api,
    identityGeneration: 1,
    user: {
      id: teacherId,
      courses,
      groups,
    },
  } as never);
  return render(
    <LocaleProvider initialLocale="en">
      <KnowledgeSetWorkspace
        agentId={agentId}
        role={role}
        initialSetId={generation?.setId}
        generationJobId={generation?.jobId}
      />
    </LocaleProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  mockedUseSession.mockReset();
  vi.restoreAllMocks();
});

describe("Knowledge Set workspace", () => {
  it("keeps the explicit AI Knowledge entry reachable in the narrow Teacher layout", async () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 390,
    });
    const api = mockApi();
    renderWorkspace(api);
    const action = await screen.findByRole("link", {
      name: "Create AI Knowledge",
    });
    action.focus();
    expect(document.activeElement).toBe(action);
    expect(action.getAttribute("href")).toBe(
      "/teacher/agents/new?flow=ai-knowledge",
    );
    expect(screen.getByRole("button", { name: "New Set" })).toBeTruthy();
  });

  it("offers Update AI Knowledge only when the writable Set exposes Agent lineage", async () => {
    const api = mockApi({
      knowledgeSet: vi.fn().mockResolvedValue({
        ...setDetail(),
        generated_by_agent_id: "agent-1",
      }),
    });
    renderWorkspace(api);
    const update = await screen.findByRole("link", {
      name: "Update AI Knowledge",
    });
    expect(update.getAttribute("href")).toBe(
      "/teacher/agents/agent-1?flow=ai-knowledge&update_set_id=set-1",
    );
    expect(api.knowledgeSet).toHaveBeenCalledWith(setId);
  });

  it("does not offer Update AI Knowledge for a non-owner projection even if it carries no usable lineage", async () => {
    const api = mockApi({
      knowledgeSet: vi.fn().mockResolvedValue({
        ...setDetail(),
        can_edit: false,
        generated_by_agent_id: null,
      }),
    });
    renderWorkspace(api);
    await screen.findAllByText("Set Alpha");
    expect(
      screen.queryByRole("link", { name: "Update AI Knowledge" }),
    ).toBeNull();
  });

  it("shows the exact generation label while the owner job is pending", async () => {
    const api = mockApi();
    renderWorkspace(api, undefined, undefined, "teacher", [], {
      jobId: "job-1",
      setId,
    });
    expect(await screen.findByText("Generating AI Knowledge")).toBeTruthy();
    expect(api.knowledgeGenerationJob).toHaveBeenCalledWith("job-1");
  });

  it("refreshes Concepts, Questions, and graph data when generation completes", async () => {
    const api = mockApi({
      knowledgeGenerationJob: vi
        .fn()
        .mockResolvedValueOnce({
          job_id: "job-1",
          run_id: "run-1",
          knowledge_set_id: setId,
          state: "pending",
          safe_error_code: null,
          accepted_item_count: 1,
          materialized_item_count: 0,
          failed_item_count: 0,
        })
        .mockResolvedValueOnce({
          job_id: "job-1",
          run_id: "run-1",
          knowledge_set_id: setId,
          state: "completed",
          safe_error_code: null,
          accepted_item_count: 1,
          materialized_item_count: 1,
          failed_item_count: 0,
        }),
      knowledgeSetAssets: vi
        .fn()
        .mockResolvedValueOnce([])
        .mockResolvedValue([conceptAsset()]),
    });
    vi.useFakeTimers();
    renderWorkspace(api, "agent-1", undefined, "teacher", [], {
      jobId: "job-1",
      setId,
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText("Generating AI Knowledge")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Concepts" }));
    expect(screen.getByText("No assets in this category yet.")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(api.knowledgeSetAssets).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: /Evaporation/ })).toBeTruthy();
    expect(api.knowledgeSet).toHaveBeenCalledTimes(2);
    expect(api.knowledgeSetGraph).toHaveBeenCalledTimes(2);
  });

  it("refreshes as items materialize and reports saved items when the run partially fails", async () => {
    const api = mockApi({
      knowledgeGenerationJob: vi
        .fn()
        .mockResolvedValueOnce({
          job_id: "job-1",
          run_id: "run-1",
          knowledge_set_id: setId,
          state: "pending",
          safe_error_code: null,
          accepted_item_count: 3,
          materialized_item_count: 0,
          failed_item_count: 0,
        })
        .mockResolvedValueOnce({
          job_id: "job-1",
          run_id: "run-1",
          knowledge_set_id: setId,
          state: "running",
          safe_error_code: null,
          accepted_item_count: 3,
          materialized_item_count: 1,
          failed_item_count: 0,
        })
        .mockResolvedValueOnce({
          job_id: "job-1",
          run_id: "run-1",
          knowledge_set_id: setId,
          state: "failed",
          safe_error_code: "knowledge_generation_partial_failure",
          accepted_item_count: 3,
          materialized_item_count: 1,
          failed_item_count: 2,
        }),
      knowledgeSetAssets: vi
        .fn()
        .mockResolvedValueOnce([])
        .mockResolvedValue([conceptAsset()]),
    });
    vi.useFakeTimers();
    renderWorkspace(api, "agent-1", undefined, "teacher", [], {
      jobId: "job-1",
      setId,
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    fireEvent.click(screen.getByRole("tab", { name: "Concepts" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(screen.getByText("Generating AI Knowledge")).toBeTruthy();
    expect(screen.getByText(/Saved items: 1; candidates: 3/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Evaporation/ })).toBeTruthy();
    expect(api.knowledgeSetAssets).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    const partial = screen.getByRole("alert");
    expect(partial.textContent).toContain("AI Knowledge was partially saved.");
    expect(partial.textContent).toContain("Saved items: 1");
    expect(partial.textContent).toContain("Failed items: 2");
    expect(partial.textContent).not.toContain("generation did not complete");
    expect(api.knowledgeSetAssets).toHaveBeenCalledTimes(3);
  });

  it("discards a late generation refresh after the Teacher selects another Set", async () => {
    const otherSetId = "set-2";
    const pendingAssets = deferred<KnowledgeAsset[]>();
    let firstSetAssetReads = 0;
    const api = mockApi({
      knowledgeSets: vi
        .fn()
        .mockResolvedValue([
          setSummary(),
          setSummary({ id: otherSetId, display_name: "Set Beta" }),
        ]),
      knowledgeSet: vi.fn().mockImplementation(async (id: string) => ({
        ...setDetail(),
        id,
        display_name: id === otherSetId ? "Set Beta" : "Set Alpha",
      })),
      knowledgeSetAssets: vi.fn().mockImplementation((id: string) => {
        if (id === setId && firstSetAssetReads++ === 0)
          return Promise.resolve([]);
        if (id === setId) return pendingAssets.promise;
        return Promise.resolve([]);
      }),
      knowledgeGenerationJob: vi
        .fn()
        .mockResolvedValueOnce({
          job_id: "job-1",
          run_id: "run-1",
          knowledge_set_id: setId,
          state: "pending",
          accepted_item_count: 1,
          materialized_item_count: 0,
          failed_item_count: 0,
        })
        .mockResolvedValueOnce({
          job_id: "job-1",
          run_id: "run-1",
          knowledge_set_id: setId,
          state: "completed",
          accepted_item_count: 1,
          materialized_item_count: 1,
          failed_item_count: 0,
        }),
    });
    vi.useFakeTimers();
    renderWorkspace(api, "agent-1", undefined, "teacher", [], {
      jobId: "job-1",
      setId,
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(firstSetAssetReads).toBe(2);
    fireEvent.click(screen.getByRole("button", { name: /Set Beta/ }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getAllByText("Set Beta").length).toBeGreaterThan(0);
    await act(async () => {
      pendingAssets.resolve([conceptAsset()]);
      await pendingAssets.promise;
    });
    fireEvent.click(screen.getByRole("tab", { name: "Concepts" }));
    expect(screen.getByText("No assets in this category yet.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Evaporation/ })).toBeNull();
  });

  it("ignores an old actor's in-flight asset read after identity scope changes", async () => {
    const oldActorAssets = deferred<KnowledgeAsset[]>();
    const staleConcept = {
      ...conceptAsset(),
      current_version: {
        ...conceptAsset().current_version,
        content: {
          kind: "concept" as const,
          title: "Stale actor asset",
          description: "Must not replace current actor data.",
          prerequisite_ids: [],
          citations: [],
        },
      },
    };
    let assetReads = 0;
    const api = mockApi({
      knowledgeGenerationJob: vi
        .fn()
        .mockResolvedValueOnce({
          job_id: "job-1",
          run_id: "run-1",
          knowledge_set_id: setId,
          state: "pending",
          accepted_item_count: 1,
          materialized_item_count: 0,
          failed_item_count: 0,
        })
        .mockResolvedValue({
          job_id: "job-1",
          run_id: "run-1",
          knowledge_set_id: setId,
          state: "completed",
          accepted_item_count: 1,
          materialized_item_count: 1,
          failed_item_count: 0,
        }),
      knowledgeSetAssets: vi.fn().mockImplementation(() => {
        assetReads += 1;
        if (assetReads === 1) return Promise.resolve([]);
        if (assetReads === 2) return oldActorAssets.promise;
        return Promise.resolve([conceptAsset()]);
      }),
    });
    vi.useFakeTimers();
    const view = renderWorkspace(api, undefined, undefined, "teacher", [], {
      jobId: "job-1",
      setId,
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    fireEvent.click(screen.getByRole("tab", { name: "Concepts" }));
    expect(screen.getByText("No assets in this category yet.")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(assetReads).toBe(2);
    mockedUseSession.mockReturnValue({
      api,
      identityGeneration: 2,
      user: {
        id: "teacher-2",
        courses: [{ course_id: courseId, role: "teacher" }],
        groups: [],
      },
    } as never);
    view.rerender(
      <LocaleProvider initialLocale="en">
        <KnowledgeSetWorkspace />
      </LocaleProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole("tab", { name: "Concepts" })).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Concepts" }));
    expect(screen.getByRole("button", { name: /Evaporation/ })).toBeTruthy();
    await act(async () => {
      oldActorAssets.resolve([staleConcept]);
      await oldActorAssets.promise;
    });
    expect(screen.getByRole("button", { name: /Evaporation/ })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /Stale actor asset/ }),
    ).toBeNull();
  });

  it("discards materialization refreshes from a superseded generation job", async () => {
    const staleJobAssets = deferred<KnowledgeAsset[]>();
    let assetReads = 0;
    let oldJobReads = 0;
    const api = mockApi({
      knowledgeGenerationJob: vi.fn(async (jobId: string) => ({
        job_id: jobId,
        run_id: `${jobId}-run`,
        knowledge_set_id: setId,
        state: jobId === "job-old" && oldJobReads++ > 0 ? "running" : "pending",
        safe_error_code: null,
        accepted_item_count: 1,
        materialized_item_count: jobId === "job-old" && oldJobReads > 1 ? 1 : 0,
        failed_item_count: 0,
      })),
      knowledgeSetAssets: vi.fn().mockImplementation(() => {
        assetReads += 1;
        if (assetReads === 1) return Promise.resolve([]);
        return staleJobAssets.promise;
      }),
    });
    vi.useFakeTimers();
    const view = renderWorkspace(api, "agent-1", undefined, "teacher", [], {
      jobId: "job-old",
      setId,
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
      for (let index = 0; index < 6; index += 1) await Promise.resolve();
    });
    fireEvent.click(screen.getByRole("tab", { name: "Concepts" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(assetReads).toBe(2);

    view.rerender(
      <LocaleProvider initialLocale="en">
        <KnowledgeSetWorkspace
          agentId="agent-1"
          role="teacher"
          initialSetId={setId}
          generationJobId="job-new"
        />
      </LocaleProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
      for (let index = 0; index < 6; index += 1) await Promise.resolve();
    });
    expect(screen.getByText("Generating AI Knowledge")).toBeTruthy();
    await act(async () => {
      staleJobAssets.resolve([conceptAsset()]);
      await staleJobAssets.promise;
    });
    expect(screen.getByText("No assets in this category yet.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Evaporation/ })).toBeNull();
  });

  it("stops on unknown Provider acceptance and directs the Teacher to reconcile without retry", async () => {
    const api = mockApi({
      knowledgeGenerationJob: vi.fn().mockResolvedValue({
        job_id: "job-1",
        run_id: "run-1",
        knowledge_set_id: setId,
        state: "interrupted",
        safe_error_code: "acceptance_unknown",
        created_at: "2026-09-27T12:00:00Z",
        updated_at: "2026-09-27T12:00:00Z",
        accepted_item_count: 1,
        materialized_item_count: 1,
        failed_item_count: 0,
      }),
    });
    renderWorkspace(api, "agent-1", undefined, "teacher", [], {
      jobId: "job-1",
      setId,
    });
    expect((await screen.findByRole("alert")).textContent).toContain(
      "acceptance unknown",
    );
    expect(
      screen.queryByRole("link", { name: "Open Agent Workbench" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: /retry generation/i }),
    ).toBeNull();
  });

  it("links a provider-confirmation block to its exact owner disclosure", async () => {
    const manifestHash = "b".repeat(64);
    const api = mockApi({
      knowledgeGenerationJob: vi.fn().mockResolvedValue({
        job_id: "job-1",
        run_id: "run-1",
        knowledge_set_id: setId,
        state: "blocked",
        safe_error_code: "provider_confirmation_required",
        provider_manifest_hash: manifestHash,
        accepted_item_count: 1,
        materialized_item_count: 0,
        failed_item_count: 0,
        created_at: "2026-09-27T12:00:00Z",
        updated_at: "2026-09-27T12:00:00Z",
      }),
    });
    renderWorkspace(api, "agent-1", undefined, "teacher", [], {
      jobId: "job-1",
      setId,
    });
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Open and confirm the exact provider disclosure for this run",
    );
    expect(
      screen
        .getByRole("link", { name: "Open provider disclosure" })
        .getAttribute("href"),
    ).toBe(`/teacher/provider-disclosures/${manifestHash}`);
  });

  it("renames on Enter or blur and makes Escape a no-write cancel", async () => {
    const api = mockApi();
    renderWorkspace(api);

    const editName = await screen.findByRole("button", {
      name: "Edit Set name: Set Alpha",
    });
    fireEvent.click(editName);
    let input = screen.getByLabelText("Set name");
    fireEvent.change(input, { target: { value: "Discarded name" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(api.updateKnowledgeSet).not.toHaveBeenCalled();
    expect(
      await screen.findByRole("button", { name: "Edit Set name: Set Alpha" }),
    ).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "Edit Set name: Set Alpha" }),
    );
    input = screen.getByLabelText("Set name");
    fireEvent.change(input, { target: { value: "Set Beta" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(api.updateKnowledgeSet).toHaveBeenCalledTimes(1),
    );
    expect(api.updateKnowledgeSet).toHaveBeenCalledWith(
      setId,
      { expected_metadata_revision: 0, display_name: "Set Beta" },
      expect.objectContaining({ idempotency: expect.any(Object) }),
    );
  });

  it("keeps every Question field intact when saving a new immutable version", async () => {
    const api = mockApi();
    renderWorkspace(api);
    fireEvent.click(await screen.findByRole("tab", { name: "Questions" }));
    fireEvent.click(
      await screen.findByRole("button", { name: /Explain evaporation/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save new version" }));

    await waitFor(() =>
      expect(api.updateKnowledgeSetAsset).toHaveBeenCalledTimes(1),
    );
    const [, body] = api.updateKnowledgeSetAsset.mock.calls[0] as [
      string,
      { content: Record<string, unknown> },
    ];
    expect(body.content.reference_answer).toBe("Teacher answer canary.");
    expect(body.content.concept_ids).toEqual([conceptId]);
    expect(body.content.citations).toEqual([
      {
        source_binding_id: bindingId,
        location: {
          section_path: ["Water cycle", "Evaporation"],
          start_offset: 19,
          end_offset: 42,
          paragraph_index: 3,
          excerpt_hash: hash,
        },
      },
    ]);
    expect(body.content.rubric).toEqual({
      criteria: [
        { label: "Cause", guidance: "Names the heat source.", points: 2 },
        { label: "Change", guidance: "Explains vaporization.", points: 3 },
      ],
      total_points: 5,
    });
  });

  it("uses the same Set IDs from the Agent entry and keeps Graph read-only", async () => {
    const api = mockApi();
    renderWorkspace(api, "agent-1");
    expect(
      await screen.findByRole("heading", {
        name: "Knowledge Sets for this Agent",
      }),
    ).toBeTruthy();
    expect(api.agentKnowledgeSets).toHaveBeenCalledWith("agent-1");

    fireEvent.click(await screen.findByRole("tab", { name: "Concepts" }));
    fireEvent.click(screen.getByRole("button", { name: "Graph" }));
    fireEvent.click(await screen.findByRole("button", { name: /Evaporation/ }));
    expect(await screen.findByText("Liquid becomes vapor.")).toBeTruthy();
    expect(api.knowledgeSetAsset).toHaveBeenCalledWith(conceptId);
    expect(screen.queryByRole("button", { name: /Edit graph/ })).toBeNull();
  });

  it("resolves an Agent entry against that Agent's course", async () => {
    const secondCourseId = "course-2";
    const api = mockApi({
      courses: vi.fn().mockResolvedValue([
        { id: courseId, code: "COURSE-1", name: "Course One" },
        { id: secondCourseId, code: "COURSE-2", name: "Course Two" },
      ]),
      agent: vi
        .fn()
        .mockResolvedValue({ id: "agent-1", course_id: secondCourseId }),
      knowledgeSets: vi.fn().mockResolvedValue([]),
      groups: vi.fn().mockResolvedValue([]),
      agentKnowledgeSets: vi.fn().mockResolvedValue({
        agent_id: "agent-1",
        agent_metadata_revision: 0,
        sets: [],
      }),
      createKnowledgeSet: vi.fn().mockResolvedValue({
        ...setDetail(),
        course_id: secondCourseId,
        display_name: "From second course",
      }),
    });
    renderWorkspace(api, "agent-1", [
      { course_id: courseId, role: "teacher" },
      { course_id: secondCourseId, role: "teacher" },
    ]);

    await screen.findByRole("heading", {
      name: "Knowledge Sets for this Agent",
    });
    expect(api.agent).toHaveBeenCalledWith("agent-1");
    expect(api.knowledgeSets).toHaveBeenCalledWith(secondCourseId);
    expect(api.groups).toHaveBeenCalledWith(secondCourseId);

    fireEvent.click(screen.getByRole("button", { name: "New Set" }));
    fireEvent.change(screen.getByLabelText("Set name"), {
      target: { value: "From second course" },
    });
    fireEvent.submit(screen.getByLabelText("Set name").closest("form")!);
    await waitFor(() =>
      expect(api.createKnowledgeSet).toHaveBeenCalledTimes(1),
    );
    expect(api.createKnowledgeSet).toHaveBeenCalledWith(
      secondCourseId,
      { display_name: "From second course" },
      expect.objectContaining({ idempotency: expect.any(Object) }),
    );
  });

  it("discards a late workspace response after the signed-in actor changes", async () => {
    let releaseOldCourses!: (
      value: Array<{ id: string; code: string; name: string }>,
    ) => void;
    const pendingOldCourses = new Promise<
      Array<{ id: string; code: string; name: string }>
    >((resolve) => {
      releaseOldCourses = resolve;
    });
    const oldApi = mockApi({
      courses: vi.fn().mockReturnValue(pendingOldCourses),
      knowledgeSets: vi.fn(),
    });
    const rendered = renderWorkspace(oldApi);
    await waitFor(() => expect(oldApi.courses).toHaveBeenCalledTimes(1));

    const nextSet = setSummary({
      id: "new-actor-set",
      owner_user_id: "teacher-2",
      display_name: "New actor Set",
    });
    const nextDetail = { ...setDetail(), ...nextSet, sources: [] };
    const nextApi = mockApi({
      knowledgeSets: vi.fn().mockResolvedValue([nextSet]),
      knowledgeSet: vi.fn().mockResolvedValue(nextDetail),
    });
    mockedUseSession.mockReturnValue({
      api: nextApi,
      identityGeneration: 2,
      user: {
        id: "teacher-2",
        courses: [{ course_id: courseId, role: "teacher" }],
        groups: [],
      },
    } as never);
    rendered.rerender(
      <LocaleProvider initialLocale="en">
        <KnowledgeSetWorkspace />
      </LocaleProvider>,
    );

    expect(await screen.findByText("New actor Set")).toBeTruthy();
    releaseOldCourses([{ id: courseId, code: "COURSE-1", name: "Course One" }]);
    await waitFor(() => expect(oldApi.knowledgeSets).not.toHaveBeenCalled());
    expect(screen.queryByText("Old actor Set")).toBeNull();
  });

  it("keeps the original source library reachable from the top-level Knowledge entry", async () => {
    const api = mockApi({
      workspaceDocuments: vi.fn().mockResolvedValue([
        {
          id: "personal-source-1",
          group_id: null,
          course_id: courseId,
          ownership_scope: "personal",
          visibility: "private",
          can_manage_visibility: true,
          authorization_epoch: 0,
          source_filename: "field-notes.md",
          char_count: 128,
          content_hash: hash,
          index_revision: 1,
          index_status: "ready",
          workspace_state: "active",
          created_at: "2026-09-27T12:00:00Z",
        },
      ]),
    });
    renderWorkspace(api);

    fireEvent.click(
      await screen.findByRole("tab", { name: "Original sources" }),
    );
    expect(await screen.findByText("field-notes.md")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open your Agents" })).toBeTruthy();
    expect(api.workspaceDocuments).toHaveBeenCalledWith(courseId);
  });

  it("explains that private asset versions stay private after a Set is shared", async () => {
    const sharedSet = setSummary({
      group_id: "group-1",
      ownership_scope: "group",
      visibility: "public",
      can_edit: true,
      asset_count: 1,
    });
    const api = mockApi({
      knowledgeSets: vi.fn().mockResolvedValue([sharedSet]),
      knowledgeSet: vi.fn().mockResolvedValue({
        ...setDetail(),
        ...sharedSet,
        sources: [],
      }),
      knowledgeSetAssets: vi.fn().mockResolvedValue([questionAsset()]),
    });
    renderWorkspace(api);

    expect(
      await screen.findByText(
        /Making this Set Public does not share content saved while it was Private/,
      ),
    ).toBeTruthy();
  });

  it("allows a Student Agent page to enter its current Knowledge Set workspace", async () => {
    const api = mockApi();
    renderWorkspace(
      api,
      "agent-1",
      [{ course_id: courseId, role: "student" }],
      "student",
    );

    expect(
      await screen.findByRole("heading", {
        name: "Knowledge Sets for this Agent",
      }),
    ).toBeTruthy();
    expect(api.agentKnowledgeSets).toHaveBeenCalledWith("agent-1");
    expect(await screen.findByRole("tab", { name: "Concepts" })).toBeTruthy();
    expect(screen.queryByRole("tab", { name: "Original sources" })).toBeNull();
    expect(
      screen.queryByRole("link", { name: "Create AI Knowledge" }),
    ).toBeNull();
  });

  it("loads a student's Public Set sources without calling the teacher-only document route", async () => {
    const sharedSet = setSummary({
      group_id: "group-1",
      ownership_scope: "group",
      visibility: "public",
      can_edit: false,
    });
    const detail = {
      ...setDetail(),
      ...sharedSet,
      sources: [
        {
          id: bindingId,
          document_id: "document-1",
          source_filename: "lesson.md",
          char_count: 240,
          content_hash: hash,
          authorization_epoch: 0,
          order_index: 0,
          is_active: true,
          available: true,
        },
      ],
    };
    const api = mockApi({
      knowledgeSets: vi.fn().mockResolvedValue([sharedSet]),
      knowledgeSet: vi.fn().mockResolvedValue(detail),
      workspaceDocuments: vi
        .fn()
        .mockRejectedValue(new Error("teacher-only 404")),
      knowledge: vi.fn().mockResolvedValue([
        {
          id: "document-1",
          group_id: "group-1",
          course_id: courseId,
          ownership_scope: "group",
          visibility: "public",
          can_manage_visibility: false,
          authorization_epoch: 0,
          source_filename: "lesson.md",
          char_count: 240,
          content_hash: hash,
          index_status: "ready",
          index_revision: 1,
          workspace_state: "active",
          created_at: "2026-09-27T12:00:00Z",
        },
      ]),
    });
    renderWorkspace(
      api,
      undefined,
      [{ course_id: courseId, role: "student" }],
      "student",
      [{ group_id: "group-1", role: "member" }],
    );

    expect(await screen.findByText("lesson.md")).toBeTruthy();
    expect(api.workspaceDocuments).not.toHaveBeenCalled();
    expect(api.knowledge).toHaveBeenCalledWith("group-1");
    expect(screen.queryByText("Request failed")).toBeNull();
  });

  it("does not show Rubric copy in the Student Question projection", async () => {
    const sharedSet = setSummary({
      group_id: "group-1",
      ownership_scope: "group",
      visibility: "public",
      can_edit: false,
    });
    const detail = { ...setDetail(), ...sharedSet, sources: [] };
    const fullQuestion = questionAsset();
    const studentQuestion = {
      ...fullQuestion,
      audience: "student",
      can_edit: false,
      current_version: {
        ...fullQuestion.current_version,
        content: {
          kind: "question",
          prompt: "Explain evaporation.",
          concept_ids: [conceptId],
          citations: [],
        },
      },
    };
    const api = mockApi({
      knowledgeSets: vi.fn().mockResolvedValue([sharedSet]),
      knowledgeSet: vi.fn().mockResolvedValue(detail),
      knowledgeSetAssets: vi.fn().mockResolvedValue([studentQuestion]),
    });
    renderWorkspace(
      api,
      undefined,
      [{ course_id: courseId, role: "student" }],
      "student",
    );
    fireEvent.click(await screen.findByRole("tab", { name: "Questions" }));
    expect(
      await screen.findByRole("button", { name: /Explain evaporation\./ }),
    ).toBeTruthy();
    expect(screen.queryByText("Rubric · teacher only")).toBeNull();
  });

  it("loads Student version history on demand without private Question fields", async () => {
    const sharedSet = setSummary({
      group_id: "group-1",
      ownership_scope: "group",
      visibility: "public",
      can_edit: false,
      asset_count: 1,
    });
    const detail = { ...setDetail(), ...sharedSet, sources: [] };
    const fullQuestion = questionAsset();
    const studentQuestion = {
      ...fullQuestion,
      audience: "student",
      can_edit: false,
      current_version_seq: null,
      current_version: {
        ...fullQuestion.current_version,
        version_seq: null,
        content: {
          kind: "question",
          prompt: "Explain evaporation.",
          concept_ids: [conceptId],
          citations: [],
        },
      },
    };
    const api = mockApi({
      knowledgeSets: vi.fn().mockResolvedValue([sharedSet]),
      knowledgeSet: vi.fn().mockResolvedValue(detail),
      knowledgeSetAssets: vi.fn().mockResolvedValue([studentQuestion]),
      knowledgeSetAssetVersions: vi.fn().mockResolvedValue({
        audience: "student",
        asset_id: fullQuestion.id,
        versions: [
          {
            ...studentQuestion.current_version,
            content: {
              kind: "question",
              prompt: "Explain evaporation.",
              concept_ids: [conceptId],
              citations: [],
            },
          },
        ],
      }),
    });
    renderWorkspace(
      api,
      undefined,
      [{ course_id: courseId, role: "student" }],
      "student",
      [{ group_id: "group-1", role: "member" }],
    );
    fireEvent.click(await screen.findByRole("tab", { name: "Questions" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Explain evaporation." }),
    );

    expect(api.knowledgeSetAssetVersions).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "History" }));
    await waitFor(() =>
      expect(api.knowledgeSetAssetVersions).toHaveBeenCalledWith(
        fullQuestion.id,
      ),
    );
    expect(
      screen
        .getByRole("button", { name: "History" })
        .getAttribute("aria-expanded"),
    ).toBe("true");
    expect(screen.queryByText("Rubric · teacher only")).toBeNull();
    expect(screen.queryByText("Teacher answer canary.")).toBeNull();
    expect(screen.queryByText("v2")).toBeNull();
  });
});
