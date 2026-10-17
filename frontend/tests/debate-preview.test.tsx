import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "../components/locale";
import {
  DebatePreview,
  type DebatePreviewSnapshot,
} from "../components/debate/preview";

afterEach(() => cleanup());

const detail: DebatePreviewSnapshot = {
  topic: "How should a community share water?",
  participants: [
    { id: "participant-a", agent_name: "River Keeper", slot: "A" },
    { id: "participant-b", agent_name: "Market Steward", slot: "B" },
  ],
  preview: { prepared_turns: 2, expected_turns: 2, ready: true },
  preview_turns: [
    {
      id: "turn-a",
      participant_id: "participant-a",
      round_no: 1,
      turn_index: 0,
      speech: "A saved speech remains available for teacher review.",
      generation_status: "failed",
      audio_ready: false,
      safe_error_code: "tts_failed",
      segments: [
        {
          text: "Shared water requires reciprocal care.",
          source_ids: ["source-a"],
          reply_to: null,
        },
      ],
      sources: [
        {
          source_id: "source-a",
          source_filename: "water-sharing.md",
          excerpt: "The village agreement describes shared maintenance.",
          query_text: "Find the agreement about shared maintenance.",
          version_label: "V1.0",
        },
      ],
    },
    {
      id: "turn-b",
      participant_id: "participant-b",
      round_no: 1,
      turn_index: 1,
      speech: "The second saved speech.",
      generation_status: "ready",
      audio_ready: true,
      segments: [],
      sources: [],
    },
  ],
};

function renderPreview(
  snapshot: DebatePreviewSnapshot,
  onRetryTurn: (turnId: string) => void = () => undefined,
) {
  return render(
    <LocaleProvider initialLocale="en">
      <DebatePreview
        detail={snapshot}
        onRetryTurn={onRetryTurn}
        openClassroomHref="/teacher/debates-beta/debate-a/control"
      />
    </LocaleProvider>,
  );
}

describe("teacher debate preview", () => {
  it.each([
    "tts_voice_unavailable",
    "tts_provider_unavailable",
    "tts_timeout",
    "tts_http_rejected",
    "tts_response_invalid",
    "tts_result_url_rejected",
    "tts_result_dns_failed",
    "tts_result_download_failed",
    "tts_audio_invalid",
  ])(
    "preserves completed text and offers Retry turn for audio soft-fail %s",
    (code) => {
      const onRetry = vi.fn();
      renderPreview(
        {
          ...detail,
          preview_turns: detail.preview_turns!.map((turn) =>
            turn.id === "turn-a"
              ? {
                  ...turn,
                  generation_status: "final_ready",
                  audio_ready: false,
                  safe_error_code: code,
                }
              : turn,
          ),
        },
        onRetry,
      );

      const card = within(screen.getByTestId("preview-turn-turn-a"));
      expect(card.getByText(detail.preview_turns![0].speech)).toBeTruthy();
      expect(card.getByText("Audio Not Ready")).toBeTruthy();
      expect(card.getByText("Audio needs attention.")).toBeTruthy();
      expect(card.getByTestId("preview-safe-error-code").textContent).toBe(code);
      const retry = card.getByRole("button", { name: "Retry turn" });
      expect(retry).toBeTruthy();
      fireEvent.click(retry);
      expect(onRetry.mock.calls).toEqual([["turn-a"]]);
      expect(screen.getByRole("link", { name: "Immerse" })).toBeTruthy();
    },
  );

  // Unknown acceptance and invalid saved text remain blocked by the backend;
  // their error display must not imply that a retry can succeed.
  it.each([
    ["tts_unreviewed", "Saved speech."],
    ["acceptance_unknown", "Saved speech."],
    ["tts_timeout", ""],
    ["tts_timeout", " \n "],
  ])(
    "preserves the failure notice and unready preview: %s / %j",
    (code, speech) => {
      renderPreview({
        ...detail,
        preview: { prepared_turns: 1, expected_turns: 2, ready: false },
        preview_turns: detail.preview_turns!.map((turn) =>
          turn.id === "turn-a"
            ? {
                ...turn,
                generation_status: "final_ready",
                safe_error_code: code,
                speech,
              }
            : turn,
        ),
      });

      const card = within(screen.getByTestId("preview-turn-turn-a"));
      expect(card.getByText("Audio Not Ready")).toBeTruthy();
      expect(
        card.getByText(
          speech.trim() ? "Audio needs attention." : "Speech needs attention.",
        ),
      ).toBeTruthy();
      expect(screen.queryByRole("link", { name: "Immerse" })).toBeNull();
    },
  );

  it.each(["pending", "failed"])(
    "retries the exact unfinished turn after a known TTS failure: %s",
    (generationStatus) => {
      const onRetry = vi.fn();
      renderPreview(
        {
          ...detail,
          preview: { prepared_turns: 1, expected_turns: 2, ready: false },
          preview_turns: detail.preview_turns!.map((turn) =>
            turn.id === "turn-a"
              ? {
                  ...turn,
                  generation_status: generationStatus,
                  safe_error_code: "tts_timeout",
                }
              : turn,
          ),
        },
        onRetry,
      );

      const card = within(screen.getByTestId("preview-turn-turn-a"));
      expect(card.getByText("Audio Not Ready")).toBeTruthy();
      expect(screen.queryByRole("link", { name: "Immerse" })).toBeNull();
      fireEvent.click(card.getByRole("button", { name: "Retry turn" }));
      expect(onRetry.mock.calls).toEqual([["turn-a"]]);
    },
  );

  it.each(["provider_not_sent", "provider_confirmation_required"])(
    "offers Retry on text-fallback and hard-failed turns: %s",
    (code) => {
      const onRetry = vi.fn();
      renderPreview(
        {
          ...detail,
          preview: { prepared_turns: 1, expected_turns: 2, ready: false },
          preview_turns: detail.preview_turns!.map((turn) => ({
            ...turn,
            generation_status: turn.id === "turn-a" ? "final_ready" : "failed",
            audio_ready: false,
            safe_error_code: turn.id === "turn-a" ? "tts_timeout" : code,
          })),
        },
        onRetry,
      );

      const buttons = screen.getAllByRole("button", { name: "Retry turn" });
      expect(buttons).toHaveLength(2);
      fireEvent.click(
        within(screen.getByTestId("preview-turn-turn-a")).getByRole("button", {
          name: "Retry turn",
        }),
      );
      fireEvent.click(
        within(screen.getByTestId("preview-turn-turn-b")).getByRole("button", {
          name: "Retry turn",
        }),
      );
      expect(onRetry.mock.calls).toEqual([["turn-a"], ["turn-b"]]);
    },
  );

  it("keeps preparation_timeout Retry turn visible without audio", () => {
    const onRetry = vi.fn();
    renderPreview(
      {
        ...detail,
        preview: { prepared_turns: 1, expected_turns: 2, ready: false },
        preview_turns: detail.preview_turns!.map((turn) =>
          turn.id === "turn-a"
            ? {
                ...turn,
                generation_status: "failed",
                audio_ready: false,
                safe_error_code: "preparation_timeout",
                speech: "",
              }
            : turn,
        ),
      },
      onRetry,
    );
    const card = within(screen.getByTestId("preview-turn-turn-a"));
    expect(card.getByText("Audio Not Ready")).toBeTruthy();
    expect(card.getByTestId("preview-safe-error-code").textContent).toBe(
      "preparation_timeout",
    );
    fireEvent.click(card.getByRole("button", { name: "Retry turn" }));
    expect(onRetry.mock.calls).toEqual([["turn-a"]]);
  });

  it("keeps saved speech visible when audio failed and exposes exact RAG mapping", () => {
    renderPreview(detail);

    expect(screen.getByTestId("debate-preview")).toBeTruthy();
    expect(screen.queryByText("Preview", { exact: true })).toBeNull();
    expect(screen.getByRole("heading", { name: detail.topic })).toBeTruthy();
    expect(
      screen.getByText("A saved speech remains available for teacher review."),
    ).toBeTruthy();
    expect(screen.getByText("Audio Not Ready")).toBeTruthy();
    expect(screen.getByText("Audio Ready")).toBeTruthy();
    expect(screen.queryByText("Saved", { exact: true })).toBeNull();
    expect(screen.getByText("Audio needs attention.")).toBeTruthy();
    expect(screen.getByTestId("preview-safe-error-code").textContent).toBe(
      "tts_failed",
    );
    expect(screen.getByRole("button", { name: "Retry turn" })).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Immerse" }).getAttribute("href"),
    ).toBe("/teacher/debates-beta/debate-a/control");

    expect(screen.getByText("Check RAG").closest("summary")?.textContent).toBe(
      "Check RAG1",
    );
    fireEvent.click(screen.getByText("Check RAG"));
    expect(screen.getByText("water-sharing.md")).toBeTruthy();
    expect(
      screen.getByText(
        "V1.0 · query: Find the agreement about shared maintenance.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("The village agreement describes shared maintenance."),
    ).toBeTruthy();
  });

  it("opens completed text Preview without audio while keeping the audio failure visible", () => {
    renderPreview({
      ...detail,
      preview: null,
      preview_turns: detail.preview_turns?.map((turn) => ({
        ...turn,
        generation_status: "final_ready",
      })),
    });
    expect(screen.getByRole("link", { name: "Immerse" })).toBeTruthy();
    expect(screen.getByText("Audio Not Ready")).toBeTruthy();
    expect(screen.getByText("Audio needs attention.")).toBeTruthy();
  });

  it("does not treat an unfinished text turn as a completed Preview", () => {
    renderPreview({ ...detail, preview: null });
    expect(screen.queryByRole("link", { name: "Immerse" })).toBeNull();
  });

  it("retries through a labeled icon button and keeps it disabled while retrying", () => {
    const retry = vi.fn();
    const view = render(
      <DebatePreview
        detail={detail}
        openClassroomHref="/classroom"
        onRetryTurn={retry}
      />,
    );
    const button = screen.getByRole("button", { name: "Retry turn" });
    expect(button.querySelector("svg")).toBeTruthy();
    expect(button.textContent).toBe("");
    fireEvent.click(button);
    expect(retry).toHaveBeenCalledWith("turn-a");
    view.rerender(
      <DebatePreview
        detail={detail}
        openClassroomHref="/classroom"
        onRetryTurn={retry}
        retryingTurnId="turn-a"
      />,
    );
    const busy = screen.getByRole("button", { name: "Retrying…" });
    expect(busy).toHaveProperty("disabled", true);
    expect(busy.getAttribute("aria-busy")).toBe("true");
    fireEvent.click(busy);
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("shows Background before the turns only when the debate has one", () => {
    const { container } = renderPreview({
      ...detail,
      background: "  The village lost a well last winter.  ",
    });

    expect(screen.getByText("Background")).toBeTruthy();
    expect(
      screen.getByText("The village lost a well last winter."),
    ).toBeTruthy();
    const cards = container.querySelectorAll("article");
    expect(cards[0].getAttribute("data-testid")).toBe("preview-background");

    cleanup();
    renderPreview({ ...detail, background: "   " });
    expect(screen.queryByText("Background")).toBeNull();
  });

  it("holds classroom access until the server preview is ready", () => {
    renderPreview({
      ...detail,
      preview: { prepared_turns: 1, expected_turns: 2, ready: false },
    });

    expect(screen.queryByRole("link", { name: "Immerse" })).toBeNull();
    expect(
      screen.getByText("A saved speech remains available for teacher review."),
    ).toBeTruthy();
    expect(screen.queryByText("Preview progress")).toBeNull();
  });
});
