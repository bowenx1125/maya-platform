import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LocaleProvider } from "../components/locale";
import {
  SpeechStream,
  type StreamTurn,
} from "../components/debate/stage/speech-stream";
import {
  normaliseVisiblePlaybackTurn,
  visibleTurnFromPlaybackStarted,
} from "../components/debate/stage/protocol";

afterEach(() => cleanup());

const labels = {
  transcript: "Public Debate",
  round: "Round",
  sources: "Sources",
  noSources: "No matched knowledge sources.",
};

function renderStream(turns: StreamTurn[]) {
  return render(
    <LocaleProvider initialLocale="en">
      <SpeechStream
        describe={() => ({ slot: "A", name: "River Keeper" })}
        emptyMessage="No published speech."
        labels={labels}
        phaseOf={() => null}
        turns={turns}
      />
    </LocaleProvider>,
  );
}

const segmentTurn: StreamTurn = {
  id: "turn-segment",
  participant_id: "participant-a",
  round_no: 1,
  speech: "First paragraph.\n\nSecond paragraph.",
  segment_turn: {
    schema_version: "segment_turn_v2",
    segments: [
      { text: "First paragraph.", source_ids: ["source-a"], reply_to: null },
      { text: "Second paragraph.", source_ids: [], reply_to: null },
    ],
  },
  source_details: [
    {
      source_id: "source-a",
      source_filename: "history.md",
      excerpt: "The agreement records shared maintenance duties.",
      query_text: "Find the shared maintenance agreement.",
      version_label: "V1.0",
    },
  ],
  sources: [],
};

describe("segments_v2 public debate presentation", () => {
  it("renders paragraphs and keeps source receipts collapsed until Check RAG opens", () => {
    renderStream([segmentTurn]);

    expect(screen.getAllByText("First paragraph.")).toHaveLength(2);
    expect(screen.getAllByText("Second paragraph.")).toHaveLength(2);
    expect(screen.getByText("Check RAG").closest("details")).toHaveProperty(
      "open",
      false,
    );

    fireEvent.click(screen.getByText("Check RAG"));
    expect(screen.getByText("history.md")).toBeTruthy();
    expect(screen.getByText("V1.0")).toBeTruthy();
    expect(
      screen.getByText("Find the shared maintenance agreement."),
    ).toBeTruthy();
    expect(
      screen.getByText("The agreement records shared maintenance duties."),
    ).toBeTruthy();
    expect(screen.getByText("General reasoning")).toBeTruthy();
  });

  it("keeps the legacy speech and source line when no segment projection exists", () => {
    renderStream([
      {
        id: "turn-legacy",
        participant_id: "participant-a",
        round_no: 1,
        speech: "Legacy speech stays as one paragraph.",
        sources: [{ source_filename: "legacy.md" }],
      },
    ]);

    expect(
      screen.getByText("Legacy speech stays as one paragraph."),
    ).toBeTruthy();
    expect(screen.getByText(/Sources:/)).toBeTruthy();
    expect(screen.getByText("legacy.md")).toBeTruthy();
  });
});

describe("segments_v2 playback read model", () => {
  it("preserves segment and source details from HTTP/WS-shaped turns", () => {
    const raw = normaliseVisiblePlaybackTurn({
      id: "turn-a",
      participant_id: "participant-a",
      round_no: 2,
      turn_index: 1,
      speech: "A paragraph.",
      retrieval_status: "matched",
      grounding_mode: "mixed",
      sources: [],
      segment_turn: {
        schema_version: "segment_turn_v2",
        segments: [
          {
            text: "A paragraph.",
            source_ids: ["source-a"],
            reply_to: null,
            support_mode: "direct",
          },
        ],
      },
      source_details: [
        {
          source_id: "source-a",
          source_filename: "history.md",
          excerpt: "An exact excerpt.",
          query_text: null,
          version_label: "V2.0",
        },
      ],
    });

    expect(raw?.segment_turn?.segments[0]?.text).toBe("A paragraph.");
    expect(raw?.segment_turn?.segments[0]?.support_mode).toBe("direct");
    expect(raw?.source_details?.[0]).toMatchObject({
      source_id: "source-a",
      query_text: null,
      version_label: "V2.0",
    });

    const started = visibleTurnFromPlaybackStarted([], raw ? [raw] : [], {
      turn_id: "turn-a",
      speech: "A paragraph.",
      segment_turn: raw?.segment_turn,
      source_details: raw?.source_details,
      sources: [],
    });
    expect(started?.segment_turn).toEqual(raw?.segment_turn);
    expect(started?.source_details).toEqual(raw?.source_details);
    if (started) renderStream([started]);
    fireEvent.click(screen.getByText("Check RAG"));
    expect(screen.getByText("Direct evidence +5")).toBeTruthy();
  });

  it("does not let malformed structured fields hide a readable speech", () => {
    const turn = normaliseVisiblePlaybackTurn({
      id: "turn-a",
      participant_id: "participant-a",
      round_no: 1,
      turn_index: 0,
      speech: "Readable legacy speech.",
      sources: [],
      segment_turn: {
        schema_version: "segment_turn_v2",
        segments: [{ text: "Missing reply relation", source_ids: [] }],
      },
      source_details: [{ source_id: "source-a" }],
    });

    expect(turn?.speech).toBe("Readable legacy speech.");
    expect(turn?.segment_turn).toBeUndefined();
    expect(turn?.source_details).toBeUndefined();
  });
});
