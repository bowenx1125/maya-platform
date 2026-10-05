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
});
