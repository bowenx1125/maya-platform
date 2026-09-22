import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

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

function renderPreview(snapshot: DebatePreviewSnapshot) {
  return render(
    <LocaleProvider initialLocale="en">
      <DebatePreview
        detail={snapshot}
        onRetryTurn={() => undefined}
        openClassroomHref="/teacher/debates-beta/debate-a/control"
      />
    </LocaleProvider>,
  );
}

describe("teacher debate preview", () => {
  it("keeps saved speech visible when audio failed and exposes exact RAG mapping", () => {
    renderPreview(detail);

    expect(
      screen.getByText("A saved speech remains available for teacher review."),
    ).toBeTruthy();
    expect(screen.getByText("Audio Not Ready")).toBeTruthy();
    expect(screen.getByText("Audio Ready")).toBeTruthy();
    expect(screen.queryByText("Saved", { exact: true })).toBeNull();
    expect(screen.getByText("Audio needs attention.")).toBeTruthy();
    expect(screen.queryByText("tts_failed")).toBeNull();
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
