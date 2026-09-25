import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PlatformApi,
  parseSseBlock,
  readSseEvents,
  SseBlockError,
} from "../lib/api/platform";
import { localizeError } from "../lib/i18n";

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
        lang: "en",
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
    expect(result.ttsErrorCode).toBe("tts_failed");
    expect(result.audioUrl).toBeNull();
  });

  it("treats tts_speech_empty as no audio and no error", async () => {
    const textDone = `event: text_done\ndata: ${JSON.stringify({
      request_id: "req-1",
      assistant_text: "[S1]",
    })}\n\n`;
    const empty = `event: tts_speech_empty\ndata: ${JSON.stringify({
      request_id: "req-1",
    })}\n\n`;
    const session = {
      id: "conversation",
      revision: 1,
      turns: [
        {
          id: "req-1",
          assistant_text: "[S1]",
          audio_url: null,
          audio_duration_ms: null,
        },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/messages:stream"))
          return sseResponse([textDone, empty]);
        return new Response(JSON.stringify(session), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    const api = new PlatformApi({
      baseUrl: "http://maya.test/api/v1",
      csrfToken: "csrf-token-csrf-token-csrf-token",
    });
    const result = await api.streamConversation("conversation", {
      request_id: "req-1",
      expected_revision: 0,
      message: "markers",
      lang: "en",
    });
    expect(result.ttsErrorCode).toBeNull();
    expect(result.audioUrl).toBeNull();
    expect(result.session.turns[0]?.audio_url ?? null).toBeNull();
  });

  it("forwards an abort signal and attaches turn audio from tts_ready", async () => {
    const controller = new AbortController();
    const textDone = `event: text_done\ndata: ${JSON.stringify({
      request_id: "req-1",
    })}\n\n`;
    const ready = `event: tts_ready\ndata: ${JSON.stringify({
      request_id: "req-1",
      audio_url: "/api/v1/conversations/conversation/audio/req-1",
      voice_profile_id: "voice",
      content_type: "audio/wav",
      audio_duration_ms: 12000,
    })}\n\n`;
    const session = {
      id: "conversation",
      revision: 1,
      turns: [{ id: "req-1", assistant_text: "Done", audio_url: null }],
    };
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/messages:stream")) {
          expect(init?.signal).toBe(controller.signal);
          return sseResponse([textDone, ready]);
        }
        return new Response(JSON.stringify(session), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const api = new PlatformApi({
      baseUrl: "http://maya.test/api/v1",
      csrfToken: "csrf-token-csrf-token-csrf-token",
    });
    const result = await api.streamConversation(
      "conversation",
      {
        request_id: "req-1",
        expected_revision: 0,
        message: "Hello",
        lang: "en",
      },
      { signal: controller.signal },
    );
    expect(result.audioUrl).toBe(
      "/api/v1/conversations/conversation/audio/req-1",
    );
    expect(result.session.turns[0]).toMatchObject({
      audio_url: "/api/v1/conversations/conversation/audio/req-1",
      audio_duration_ms: 12000,
    });
    controller.abort();
    await expect(
      api.streamConversation(
        "conversation",
        {
          request_id: "req-2",
          expected_revision: 1,
          message: "Next",
          lang: "en",
        },
        { signal: controller.signal },
      ),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("chat error code translation", () => {
  it("translates chat_turn_closed in en and zh", () => {
    expect(localizeError({ code: "chat_turn_closed" }, "en")).toBe(
      "This reply was interrupted before it finished.",
    );
    expect(localizeError({ code: "chat_turn_closed" }, "zh")).toBe(
      "这条回复在完成前被中断。",
    );
  });
});
