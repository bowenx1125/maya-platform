import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ChatRequestPendingError,
  PlatformApi,
  parseSseBlock,
  readSseEvents,
  SseBlockError,
} from "../lib/api/platform";

afterEach(() => {
  vi.unstubAllGlobals();
});

function sseResponse(chunks: string[], gate?: Promise<void>): Response {
  const encoder = new TextEncoder();
  let index = 0;
  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (gate && index === 1) await gate;
      if (index >= chunks.length) {
        controller.close();
        return;
      }
      controller.enqueue(encoder.encode(chunks[index]));
      index += 1;
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("chat SSE parsing", () => {
  it("rejects a bad JSON block and releases the reader", async () => {
    const response = sseResponse(["event: delta\ndata: {not-json\n\n"]);
    await expect(
      readSseEvents(response, () => undefined),
    ).rejects.toBeInstanceOf(SseBlockError);
    expect(response.body?.locked).toBe(false);
    expect(() =>
      parseSseBlock('event: delta\ndata: {"ok":true}'),
    ).not.toThrow();
  });

  it("refreshes on text_done before the rest of the stream and returns a later TTS error", async () => {
    let releaseRest: () => void = () => undefined;
    const rest = new Promise<void>((resolve) => {
      releaseRest = resolve;
    });
    const textDone = `event: text_done\ndata: ${JSON.stringify({
      request_id: "req-1",
      assistant_text: "Done",
      revision: 1,
      sources: [],
    })}\n\n`;
    const ttsError = `event: error\ndata: ${JSON.stringify({
      request_id: "req-1",
      safe_error_code: "tts_failed",
    })}\n\n`;
    const session = {
      id: "conversation",
      revision: 1,
      turns: [{ id: "req-1", assistant_text: "Done", state: "ready" }],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/messages:stream"))
        return sseResponse([textDone, ttsError], rest);
      return new Response(JSON.stringify(session), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = new PlatformApi({
      baseUrl: "http://maya.test/api/v1",
      csrfToken: "csrf-token-csrf-token-csrf-token",
    });
    let refreshed = false;
    const pending = api.streamConversation(
      "conversation",
      {
        request_id: "req-1",
        expected_revision: 0,
        message: "Hello",
      },
      {
        onTextDone: (value) => {
          refreshed = value.id === "conversation";
        },
      },
    );
    await vi.waitFor(() => expect(refreshed).toBe(true));
    let settled = false;
    void pending.then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);
    releaseRest();
    const result = await pending;
    expect(result.session).toMatchObject({ id: "conversation" });
    expect(Object.keys(result)).toEqual(["session"]);
  });

  it("refreshes the saved session on a terminal chat error before rejecting", async () => {
    const terminalError = `event: error\ndata: ${JSON.stringify({
      request_id: "req-unknown",
      safe_error_code: "chat_acceptance_unknown",
    })}\n\n`;
    const session = {
      id: "conversation",
      revision: 1,
      turns: [
        {
          id: "req-unknown",
          user_text: "A preserved question",
          assistant_text: null,
          state: "acceptance_unknown",
          sources: [],
        },
      ],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/messages:stream")) return sseResponse([terminalError]);
      return new Response(JSON.stringify(session), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = new PlatformApi({
      baseUrl: "http://maya.test/api/v1",
      csrfToken: "csrf-token-csrf-token-csrf-token",
    });
    const onTerminalError = vi.fn();
    await expect(
      api.streamConversation(
        "conversation",
        {
          request_id: "req-unknown",
          expected_revision: 0,
          message: "A preserved question",
        },
        { onTerminalError },
      ),
    ).rejects.toMatchObject({ status: 502, code: "chat_acceptance_unknown" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onTerminalError).toHaveBeenCalledWith(
      session,
      expect.objectContaining({ code: "chat_acceptance_unknown" }),
    );
  });

  it("keeps a pending replay observable instead of treating it as terminal", async () => {
    const pendingEvent = `event: pending\ndata: ${JSON.stringify({
      request_id: "req-pending",
    })}\n\n`;
    const session = {
      id: "conversation",
      revision: 1,
      turns: [
        {
          id: "req-pending",
          user_text: "Still generating",
          assistant_text: null,
          state: "pending",
          sources: [],
        },
      ],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/messages:stream")) {
        return sseResponse([pendingEvent]);
      }
      return new Response(JSON.stringify(session), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = new PlatformApi({
      baseUrl: "http://maya.test/api/v1",
      csrfToken: "csrf-token-csrf-token-csrf-token",
    });
    const onPending = vi.fn();
    const onTerminalError = vi.fn();
    await expect(
      api.streamConversation(
        "conversation",
        {
          request_id: "req-pending",
          expected_revision: 0,
          message: "Still generating",
        },
        { onPending, onTerminalError },
      ),
    ).rejects.toBeInstanceOf(ChatRequestPendingError);
    expect(onPending).toHaveBeenCalledWith(session, "req-pending");
    expect(onTerminalError).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("recovers a ready turn when an intermediary returns HTTP 502", async () => {
    const session = {
      id: "conversation",
      revision: 1,
      turns: [
        {
          id: "req-saved",
          user_text: "Saved before proxy failure",
          assistant_text: "Saved answer",
          state: "ready",
          sources: [],
        },
      ],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/messages:stream")) {
        return new Response("Proxy closed after server commit", {
          status: 502,
        });
      }
      return new Response(JSON.stringify(session), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = new PlatformApi({
      baseUrl: "http://maya.test/api/v1",
      csrfToken: "csrf-token-csrf-token-csrf-token",
    });
    const onTextDone = vi.fn();
    const onTerminalError = vi.fn();
    const result = await api.streamConversation(
      "conversation",
      {
        request_id: "req-saved",
        expected_revision: 0,
        message: "Saved before proxy failure",
      },
      { onTextDone, onTerminalError },
    );
    expect(result.session).toEqual(session);
    expect(onTextDone).toHaveBeenCalledWith(session);
    expect(onTerminalError).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
