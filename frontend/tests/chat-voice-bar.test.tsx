import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  api: {} as Record<string, ReturnType<typeof vi.fn>>,
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    user: { courses: [{ course_id: "course", role: "teacher" }], groups: [] },
  }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/teacher/chat",
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("../components/avatar", () => ({
  AvatarPreview: () => <div data-testid="avatar" />,
}));

import { AgentChat } from "../components/agent-chat";
import { LocaleProvider } from "../components/locale";
import { localizeError, messages } from "../lib/i18n";

const agent = {
  agent_id: "agent",
  version_id: "version",
  course_id: "course",
  name: "Socrates",
  version_label: "V1.0",
  avatar_config: {},
};

function turn(
  id: string,
  userText: string,
  audio: { url: string; durationMs: number } | null,
) {
  return {
    id,
    user_text: userText,
    assistant_text: `${userText} reply`,
    mode: "mock",
    state: "ready",
    sources: [],
    safe_error_code: null,
    audio_url: audio?.url ?? null,
    audio_duration_ms: audio?.durationMs ?? null,
  };
}

function session(
  id: string,
  userText: string,
  audio: { url: string; durationMs: number } | null,
) {
  return {
    id,
    agent,
    revision: 1,
    created_at: "2026-09-22T00:00:00Z",
    turns: [turn(`${id}-turn`, userText, audio)],
  };
}

const older = {
  id: "older",
  agent,
  revision: 1,
  created_at: "2026-09-22T00:00:00Z",
  turns: [
    turn("older-long", "Older question", {
      url: "/api/v1/conversations/older/audio/older-long",
      durationMs: 12000,
    }),
    turn("older-short", "Follow-up", {
      url: "/api/v1/conversations/older/audio/older-short",
      durationMs: 1000,
    }),
  ],
};
const newer = session("newer", "Newer question", {
  url: "/api/v1/conversations/newer/audio/newer-turn",
  durationMs: 400,
});
const silent = session("silent", "Silent question", null);

beforeEach(() => {
  state.api = {
    chatAgents: vi.fn().mockResolvedValue([agent]),
    conversations: vi.fn().mockResolvedValue([older, newer, silent]),
    createConversation: vi.fn(),
    deleteConversation: vi.fn().mockResolvedValue(undefined),
    streamConversation: vi.fn().mockResolvedValue({
      session: newer,
      audioUrl: null,
      voiceProfileId: null,
      contentType: null,
      ttsErrorCode: null,
    }),
  };
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(
    () => undefined,
  );
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("chat voice bars", () => {
  it("shows a duration bar only for turns with audio and does not autoplay history", async () => {
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    expect(
      await screen.findByRole("button", { name: "Play voice message, 12″" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Play voice message, 1″" }),
    ).toBeTruthy();
    expect(screen.queryByText("Silent question reply")).toBeNull();
    expect(
      screen.getAllByRole("button", { name: /voice message/ }),
    ).toHaveLength(2);
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Silent question" }));
    expect(screen.getByText("Silent question reply")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /voice message/ })).toBeNull();
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });

  it("plays one bar at a time and stops it on a second click", async () => {
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    const first = await screen.findByRole("button", {
      name: "Play voice message, 12″",
    });
    const second = screen.getByRole("button", {
      name: "Play voice message, 1″",
    });
    fireEvent.click(first);
    expect(first.getAttribute("data-playing")).toBe("true");
    expect(second.getAttribute("data-playing")).toBe("false");
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Stop voice message, 12″" }),
    );
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
    expect(
      screen
        .getByRole("button", { name: "Play voice message, 12″" })
        .getAttribute("data-playing"),
    ).toBe("false");
    fireEvent.click(
      screen.getByRole("button", { name: "Play voice message, 12″" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Play voice message, 1″" }),
    );
    expect(
      screen
        .getByRole("button", { name: "Play voice message, 12″" })
        .getAttribute("data-playing"),
    ).toBe("false");
    expect(
      screen
        .getByRole("button", { name: "Stop voice message, 1″" })
        .getAttribute("data-playing"),
    ).toBe("true");
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(3);
  });

  it("autoplays only the reply that just finished", async () => {
    const empty = {
      id: "fresh",
      agent,
      revision: 0,
      created_at: "2026-09-22T00:00:00Z",
      turns: [],
    };
    const requestId = "00000000-0000-4000-8000-000000000001";
    vi.spyOn(crypto, "randomUUID").mockReturnValue(requestId);
    const spoken = session("fresh", "Hello", {
      url: "/api/v1/conversations/fresh/audio/req",
      durationMs: 2000,
    });
    spoken.turns[0].id = requestId;
    state.api.conversations.mockResolvedValue([]);
    state.api.createConversation.mockResolvedValue(empty);
    state.api.streamConversation.mockResolvedValue({
      session: { ...spoken, revision: 1 },
      audioUrl: spoken.turns[0].audio_url,
      voiceProfileId: "voice",
      contentType: "audio/wav",
      ttsErrorCode: null,
    });
    render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    fireEvent.change(await screen.findByRole("textbox", { name: "Message" }), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const bar = await screen.findByRole("button", {
      name: "Stop voice message, 2″",
    });
    expect(bar.getAttribute("data-playing")).toBe("true");
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1);
  });

  it("aborts the stream and stops audio when the conversation changes or the page closes", async () => {
    let signal: AbortSignal | undefined;
    state.api.streamConversation.mockImplementation(
      (_id: string, _body: unknown, hooks: { signal?: AbortSignal }) => {
        signal = hooks.signal;
        return new Promise(() => undefined);
      },
    );
    const view = render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    const first = await screen.findByRole("button", {
      name: "Play voice message, 12″",
    });
    fireEvent.click(first);
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "Still talking" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Still talking");
    expect(signal?.aborted).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Newer question" }));
    expect(signal?.aborted).toBe(true);
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
    expect(screen.queryByText("Still talking")).toBeNull();
    view.unmount();
  });

  it("aborts an in-flight stream when the chat unmounts", async () => {
    let signal: AbortSignal | undefined;
    state.api.conversations.mockResolvedValue([]);
    state.api.createConversation.mockResolvedValue({
      id: "fresh",
      agent,
      revision: 0,
      turns: [],
      created_at: "2026-09-22T00:00:00Z",
    });
    state.api.streamConversation.mockImplementation(
      (_id: string, _body: unknown, hooks: { signal?: AbortSignal }) => {
        signal = hooks.signal;
        return new Promise(() => undefined);
      },
    );
    const view = render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    fireEvent.change(await screen.findByRole("textbox", { name: "Message" }), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Hello");
    expect(signal?.aborted).toBe(false);
    view.unmount();
    expect(signal?.aborted).toBe(true);
  });

  it("shows a translated TTS failure instead of the raw code", async () => {
    state.api.conversations.mockResolvedValue([]);
    state.api.createConversation.mockResolvedValue({
      id: "fresh",
      agent,
      revision: 0,
      turns: [],
      created_at: "2026-09-22T00:00:00Z",
    });
    state.api.streamConversation.mockResolvedValue({
      session: {
        id: "fresh",
        agent,
        revision: 1,
        created_at: "2026-09-22T00:00:00Z",
        turns: [
          {
            id: "req",
            user_text: "Hello",
            assistant_text: "A considered reply",
            mode: "mock",
            state: "ready",
            sources: [],
            safe_error_code: null,
            audio_url: null,
            audio_duration_ms: null,
          },
        ],
      },
      audioUrl: null,
      voiceProfileId: null,
      contentType: null,
      ttsErrorCode: "tts_timeout",
    });
    render(
      <LocaleProvider initialLocale="zh">
        <AgentChat />
      </LocaleProvider>,
    );
    fireEvent.change(await screen.findByRole("textbox", { name: "Message" }), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(messages.zh.errorTtsTimeout);
    expect(alert.textContent).not.toContain("tts_timeout");
    expect(alert.textContent).not.toContain(
      messages.zh.errorProviderUnavailable,
    );
  });
});

describe("TTS error copy", () => {
  it("maps provider codes in both locales without using a generic server failure", () => {
    for (const [code, key] of [
      ["tts_failed", "errorTtsFailed"],
      ["tts_voice_unavailable", "errorTtsVoiceUnavailable"],
      ["tts_audio_invalid", "errorTtsAudioInvalid"],
      ["tts_timeout", "errorTtsTimeout"],
      ["tts_http_rejected", "errorTtsHttpRejected"],
      ["tts_response_invalid", "errorTtsResponseInvalid"],
      ["tts_result_url_rejected", "errorTtsResultUrlRejected"],
      ["tts_result_dns_failed", "errorTtsResultDnsFailed"],
      ["tts_result_download_failed", "errorTtsResultDownloadFailed"],
      ["tts_outcome_unknown", "errorTtsOutcomeUnknown"],
      ["tts_provider_error", "errorTtsProviderError"],
    ] as const) {
      expect(localizeError({ code, status: 502 }, "en")).toBe(messages.en[key]);
      expect(localizeError({ code, status: 502 }, "zh")).toBe(messages.zh[key]);
      expect(localizeError({ code, status: 502 }, "en")).not.toBe(code);
    }
  });
});

describe("voice bar mount cleanup", () => {
  it("does not apply a stream result after the view has closed", async () => {
    let release!: (value: unknown) => void;
    state.api.conversations.mockResolvedValue([]);
    state.api.createConversation.mockResolvedValue({
      id: "fresh",
      agent,
      revision: 0,
      turns: [],
      created_at: "2026-09-22T00:00:00Z",
    });
    state.api.streamConversation.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    const view = render(
      <LocaleProvider initialLocale="en">
        <AgentChat />
      </LocaleProvider>,
    );
    fireEvent.change(await screen.findByRole("textbox", { name: "Message" }), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Hello");
    view.unmount();
    await act(async () => {
      release({
        session: session("fresh", "Hello", {
          url: "/audio",
          durationMs: 1000,
        }),
        audioUrl: "/audio",
        voiceProfileId: null,
        contentType: "audio/wav",
        ttsErrorCode: "tts_failed",
      });
    });
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });
});
