import {
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
      <KnowledgeSetWorkspace agentId={agentId} role={role} />
    </LocaleProvider>,
  );
}

afterEach(() => {
  cleanup();
  mockedUseSession.mockReset();
  vi.restoreAllMocks();
});

describe("Knowledge Set workspace", () => {
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
