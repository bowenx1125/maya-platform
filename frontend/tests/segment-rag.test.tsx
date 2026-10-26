import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

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

function renderStream(
  turns: StreamTurn[],
  activeReveal?: { turnId: string; progress: number },
) {
  return render(
    <>
      <SpeechStream
        activeReveal={activeReveal}
        // Callers pass their own class map since the classic stage CSS was removed.
        styles={{
          streamItem: "streamItem",
          streamParagraphs: "streamParagraphs",
          streamSpeech: "streamSpeech",
        }}
        describe={() => ({ slot: "A", name: "River Keeper" })}
        emptyMessage="No published speech."
        labels={labels}
        phaseOf={() => null}
        turns={turns}
      />
    </>,
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
  it("reveals the active structured speech with audio progress and leaves history whole", () => {
    const history = { ...segmentTurn, id: "history" };
    const view = renderStream([history, segmentTurn], {
      turnId: segmentTurn.id,
      progress: 0.5,
    });

    const articles = view.container.querySelectorAll(
      'article[class*="streamItem"]',
    );
    const historySpeech = articles[0]?.querySelector(
      'div[class*="streamParagraphs"]',
    );
    const activeSpeech = articles[1]?.querySelector(
      'div[class*="streamParagraphs"]',
    );
    expect(historySpeech?.textContent).toContain("Second paragraph.");
    expect(activeSpeech?.textContent).not.toContain("Second paragraph.");

    view.rerender(
      <>
        <SpeechStream
          activeReveal={{ turnId: segmentTurn.id, progress: 1 }}
          describe={() => ({ slot: "A", name: "River Keeper" })}
          emptyMessage="No published speech."
          labels={labels}
          phaseOf={() => null}
          turns={[history, segmentTurn]}
        />
      </>,
    );
    expect(activeSpeech?.textContent).toContain("Second paragraph.");
  });

  it("shows the frozen anonymous message beside its reply without rewriting speech", () => {
    const turn: StreamTurn = {
      ...segmentTurn,
      round_no: 4,
      segment_turn: {
        schema_version: "segment_turn_v2",
        segments: [
          {
            text: "First paragraph.",
            source_ids: [],
            reply_to: "B1",
            reply_text: "How can [redacted] challenge the criterion?",
          },
          { text: "Second paragraph.", source_ids: [], reply_to: null },
        ],
      },
    };
    const view = renderStream([turn]);
    const quote = screen.getByRole("blockquote", {
      name: "In reply to a classroom message",
    });
    expect(quote.textContent).toContain(
      "How can [redacted] challenge the criterion?",
    );
    expect(view.container.querySelectorAll("blockquote")).toHaveLength(1);
    expect(quote.nextElementSibling?.textContent).toBe("First paragraph.");
    expect(turn.speech).toBe("First paragraph.\n\nSecond paragraph.");
  });

  it("keeps older reply references readable without inventing missing classroom text", () => {
    renderStream([
      {
        ...segmentTurn,
        segment_turn: {
          schema_version: "segment_turn_v2",
          segments: [
            { text: "Existing reply.", source_ids: [], reply_to: "B1" },
          ],
        },
      },
    ]);
    expect(screen.queryByRole("blockquote")).toBeNull();
    expect(screen.getAllByText("Existing reply.").length).toBeGreaterThan(0);
  });

  it("renders paragraphs and keeps source receipts collapsed until Check RAG opens", () => {
    renderStream([segmentTurn]);

    expect(screen.getByText("Check RAG").closest("summary")?.textContent).toBe(
      "Check RAG1",
    );
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

  it("reveals an unstructured active speech by progress without changing the source", () => {
    const turn: StreamTurn = {
      id: "legacy-progress",
      participant_id: "participant-a",
      round_no: 1,
      speech: "自由与责任相辅相成。",
    };
    const view = renderStream([turn], { turnId: turn.id, progress: 0.5 });
    const speech = view.container.querySelector(
      'article[class*="streamItem"] > p[class*="streamSpeech"]',
    );
    expect(speech?.textContent).toContain("自由与责任");
    expect(speech?.textContent).not.toContain("相辅相成");
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
            reply_to: "B1",
            reply_text: "A frozen anonymous classroom question.",
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

    expect(raw?.segment_turn?.segments[0]?.reply_text).toBe(
      "A frozen anonymous classroom question.",
    );
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
