import { afterEach, describe, expect, it, vi } from "vitest";

import { createIdempotencyHandle, PlatformApi } from "../lib/api/platform";

afterEach(() => vi.restoreAllMocks());

describe("PlatformApi Brainform actions", () => {
  it("posts the durable Memory action with the exact course and source identity", async () => {
    const response = {
      action_id: "11111111-1111-4111-8111-111111111111",
      conversation_id: "22222222-2222-4222-8222-222222222222",
      request_id: "33333333-3333-4333-8333-333333333333",
      message: "你目前记得我们之前聊过什么？",
      session: {},
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify(response), { status: 200 }),
      );
    const api = new PlatformApi({
      baseUrl: "/api/v1",
      csrfToken: "csrf-token",
    });
    const body = {
      action_id: response.action_id,
      course_id: "44444444-4444-4444-8444-444444444444",
      source: {
        kind: "agent" as const,
        agent_id: "55555555-5555-4555-8555-555555555555",
      },
    };

    expect(await api.memoryEntry(body)).toEqual(response);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/conversations/memory-entry",
    );
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": "csrf-token",
      },
    });
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual(body);
  });

  it("uses empty-body owner controls and preserves the request action in the URL", async () => {
    const session = { id: "conversation-1" };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify(session), { status: 200 }),
      );
    const api = new PlatformApi({
      baseUrl: "/api/v1",
      csrfToken: "csrf-token",
    });

    await api.controlConversationTurn("conversation-1", "turn-1", "resume");
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/conversations/conversation-1/turns/turn-1:resume",
    );
    expect(fetchMock.mock.calls[0][1]?.method).toBe("POST");
    expect(fetchMock.mock.calls[0][1]?.body).toBeUndefined();
    expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({
      "X-CSRF-Token": "csrf-token",
    });
    expect(fetchMock.mock.calls[0][1]?.headers).not.toHaveProperty(
      "Idempotency-Key",
    );
  });

  it("posts an idempotent lifecycle action to the current assessment attempt", async () => {
    const result = { response_key: "assessment.paused" };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(result), { status: 200 }));
    const api = new PlatformApi({
      baseUrl: "/api/v1",
      csrfToken: "csrf-token",
    });
    const body = {
      client_event_id: "11111111-1111-4111-8111-111111111111",
      action: "pause" as const,
    };

    expect(await api.assessmentAttemptAction("attempt-1", body)).toEqual(
      result,
    );
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/learning/attempts/attempt-1/actions",
    );
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": "csrf-token",
      },
    });
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual(body);
  });

  it("renames a Markdown source through metadata CAS rather than replacing its bytes", async () => {
    const document = {
      id: "document-1",
      source_filename: "old.md",
      content_hash: "a".repeat(64),
      index_revision: 3,
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify(document), { status: 200 }),
      );
    const api = new PlatformApi({
      baseUrl: "/api/v1",
      csrfToken: "csrf-token",
    });
    const idempotency = createIdempotencyHandle();
    const idempotencyKey = idempotency.key;

    expect(
      await api.renameKnowledgeDocument(
        "document-1",
        { expected_filename: "old.md", filename: "new.md" },
        { idempotency },
      ),
    ).toEqual(document);
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/knowledge-documents/document-1:rename",
    );
    expect(fetchMock.mock.calls[0][1]?.method).toBe("POST");
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      expected_filename: "old.md",
      filename: "new.md",
    });
    expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({
      "Idempotency-Key": idempotencyKey,
      "X-CSRF-Token": "csrf-token",
    });
  });

  it("retains canonical Markdown sequence CAS, asset history, Graph, and generation linkage APIs", async () => {
    const generatedRow = {
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      generation_job_id: "job-1",
      can_read: true,
      can_edit: true,
      version_seq: 4,
      content_hash: "a".repeat(64),
      generation_state: "completed",
      safe_error_code: null,
    };
    const markdown = {
      audience: "full",
      agent_id: "agent-1",
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      version_seq: 4,
      content_hash: "a".repeat(64),
      markdown: "# Canonical Knowledge",
      projection_available: true,
      can_read: true,
      can_edit: true,
      created_at: "2026-10-07T00:00:00Z",
    };
    const assetVersions = {
      asset_id: "asset-1",
      audience: "student",
      versions: [],
    };
    const graph = {
      set_id: "set-1",
      nodes: [],
      edges: [],
    };
    const savedMarkdown = {
      ...markdown,
      version_seq: 5,
      markdown: "# Updated",
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify([generatedRow]), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(markdown), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(assetVersions), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(graph), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(savedMarkdown), { status: 200 }),
      );
    const api = new PlatformApi({
      baseUrl: "http://maya.test/api/v1",
      csrfToken: "csrf-token",
    });
    const generationRows = await api.brainformKnowledge("course-1");

    expect(generationRows[0]).toMatchObject({
      canonical_set_id: "set-1",
      generation_job_id: "job-1",
    });
    expect(await api.knowledgeMarkdown("set-1")).toMatchObject({
      canonical_set_id: "set-1",
      version_seq: 4,
    });
    expect(await api.knowledgeSetAssetVersions("asset-1")).toEqual(
      assetVersions,
    );
    expect(await api.knowledgeSetGraph("set-1")).toEqual(graph);

    const idempotency = createIdempotencyHandle();
    const idempotencyKey = idempotency.key;
    expect(
      await api.saveKnowledgeMarkdown(
        "set-1",
        { expected_version_seq: 4, markdown: "# Updated" },
        { idempotency },
      ),
    ).toMatchObject({ canonical_set_id: "set-1", version_seq: 5 });

    expect(new URL(String(fetchMock.mock.calls[4]?.[0])).pathname).toBe(
      "/api/v1/knowledge-sets/set-1/markdown",
    );
    expect(fetchMock.mock.calls[4]?.[1]).toMatchObject({
      method: "PUT",
      headers: {
        "Idempotency-Key": idempotencyKey,
        "X-CSRF-Token": "csrf-token",
      },
    });
    expect(JSON.parse(String(fetchMock.mock.calls[4]?.[1]?.body))).toEqual({
      expected_version_seq: 4,
      markdown: "# Updated",
    });
  });
});

describe("PlatformApi RAG +", () => {
  // The Brainform RAG + adds to the shared pool Brainform lists: public, in
  // no Agent (no target_agent_version_id), on the same library endpoints.
  it.each([
    [{ courseId: "course-1" }, "/api/v1/courses/course-1/workspace-documents"],
    [{ groupId: "group-1" }, "/api/v1/groups/group-1/knowledge-documents"],
  ])("posts %o as a shared library RAG", async (target, url) => {
    const document = { id: "document-new" };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ document, agent_version: null }), {
        status: 201,
      }),
    );
    // Read the multipart fields as the adapter writes them.
    const fields: Record<string, unknown> = {};
    const append = FormData.prototype.append;
    vi.spyOn(FormData.prototype, "append").mockImplementation(function (
      this: FormData,
      name: string,
      value: string | Blob,
    ) {
      fields[name] = value;
      Reflect.apply(append, this, [name, value]);
    });
    const api = new PlatformApi({
      baseUrl: "http://localhost/api/v1",
      csrfToken: "csrf",
    });
    const file = new File(["# Notes"], "Notes.md", { type: "text/markdown" });
    expect(await api.uploadRagLibraryDocument(target, file)).toEqual(document);
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.url).toBe(`http://localhost${url}`);
    expect(request.method).toBe("POST");
    expect(fields.visibility).toBe("public");
    expect(fields).not.toHaveProperty("target_agent_version_id");
    expect(fields).not.toHaveProperty("expected_revision");
    expect((fields.file as File).name).toBe("Notes.md");
  });
});
