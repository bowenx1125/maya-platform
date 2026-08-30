import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "../components/locale";
import {
  HistoryView,
  InteractionHistory,
  TranscriptHistory,
  type HistoryInteraction,
  type HistoryReport,
  type HistoryTranscript,
} from "../components/history";
import {
  TranslationPanel,
  type TranslationBatch,
} from "../components/translation";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const turnId = "40000000-0000-4000-8000-000000000001";
const debateId = "20000000-0000-4000-8000-000000000001";
const participantId = "30000000-0000-4000-8000-000000000001";

const transcript: HistoryTranscript = {
  debate_id: debateId,
  audio_retained: false,
  turns: [
    {
      id: turnId,
      participant_id: participantId,
      round_no: 1,
      turn_index: 0,
      speech: "Authoritative English speech.",
      retrieval_status: "matched",
      grounding_mode: "rag_grounded",
      sources: [{ source_filename: "evidence.md" }],
      translated_text:
        "【测试中文表示，不代表翻译质量】\nAuthoritative English speech.",
    },
  ],
};

const interaction: HistoryInteraction = {
  status: "finalized",
  votes: [
    {
      participant_id: participantId,
      count: 3,
      percentage: 75,
      slot: "A",
      participant_name: "Bowen",
    },
  ],
  barrages: [
    {
      id: "41000000-0000-4000-8000-000000000001",
      nickname: "Learner",
      raw_text: "A thoughtful question.",
      sequence: 1,
      submitted_at: "2026-08-29T00:00:00Z",
    },
  ],
};

const report: HistoryReport = {
  generation_status: "ready",
  latest_attempt_status: "ready",
  current_success_revision: {
    id: "42000000-0000-4000-8000-000000000001",
    revision_no: 1,
    status: "ready",
    word_count: 650,
    safe_error_code: null,
    created_at: "2026-08-29T00:00:00Z",
    english_markdown:
      "# Civilization Mutual Learning Report\n\nEnglish report.",
    translated_markdown: null,
  },
  revisions: [
    {
      id: "42000000-0000-4000-8000-000000000001",
      revision_no: 1,
      status: "ready",
      word_count: 650,
      safe_error_code: null,
      created_at: "2026-08-29T00:00:00Z",
    },
  ],
};

const batch: TranslationBatch = {
  id: "43000000-0000-4000-8000-000000000001",
  debate_id: debateId,
  input_hash: "a".repeat(64),
  status: "partial",
  target_language: "zh-Hans",
  quality: "test_representation",
  total_items: 2,
  succeeded_items: 1,
  failed_items: 1,
  items: [
    {
      content_type: "turn",
      content_id: turnId,
      source_text_hash: "b".repeat(64),
      status: "ready",
      reused: false,
      safe_error_code: null,
    },
    {
      content_type: "report_revision",
      content_id: "42000000-0000-4000-8000-000000000001",
      source_text_hash: "c".repeat(64),
      status: "failed",
      reused: false,
      safe_error_code: "translation_provider_failed",
    },
  ],
  created_at: "2026-08-29T00:00:00Z",
  updated_at: "2026-08-29T00:00:01Z",
};

function renderEnglish(children: React.ReactNode) {
  return render(<LocaleProvider initialLocale="en">{children}</LocaleProvider>);
}

describe("Wave 3 M15 history and translation UI", () => {
  it("keeps authoritative English, source filename, and audio retention boundary visible", () => {
    renderEnglish(<TranscriptHistory transcript={transcript} />);

    expect(screen.getByText("Authoritative English speech.")).toBeTruthy();
    expect(screen.getByText("evidence.md")).toBeTruthy();
    expect(screen.queryByText(/Test translation/)).toBeNull();
    expect(
      screen.getByText("Audio is no longer retained for this debate"),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Text, sources and derived translations remain available in history.",
      ),
    ).toBeTruthy();
  });

  it("shows raw named barrages and anonymous vote totals as separate history sections", () => {
    renderEnglish(<InteractionHistory interaction={interaction} />);

    expect(screen.getByText("Learner")).toBeTruthy();
    expect(screen.getByText("A thoughtful question.")).toBeTruthy();
    expect(screen.getByText(/Bowen/)).toBeTruthy();
    expect(screen.getByText(/3 · 75%/)).toBeTruthy();
    expect(screen.queryByText("Learner · 3 · 75%")).toBeNull();
  });

  it("shows the current Maya report and does not hide it when history has no audio", () => {
    renderEnglish(
      <HistoryView
        topic="A debate topic"
        transcript={transcript}
        interaction={interaction}
        report={report}
      />,
    );

    expect(screen.getByText("Current successful revision: v1")).toBeTruthy();
    expect(
      screen.getByText(/Civilization Mutual Learning Report/),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "History is read-only; playback availability follows the course audio pointer.",
      ),
    ).toBeTruthy();
  });

  it("renders a visible Mock disclaimer and partial item error without exposing provider fields", () => {
    const onTranslate = vi.fn();
    const onToggleDisplay = vi.fn();
    renderEnglish(
      <TranslationPanel
        batches={[batch]}
        onTranslate={onTranslate}
        onToggleDisplay={onToggleDisplay}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Show Chinese speeches" }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Mock representation only; it does not claim translation quality and never feeds debate generation, RAG, TTS or reports.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("1/2 succeeded")).toBeTruthy();
    expect(screen.getByText("translation_provider_failed")).toBeTruthy();
    expect(screen.queryByText("provider")).toBeNull();
    screen.getByRole("button", { name: "Show Chinese speeches" }).click();
    expect(onToggleDisplay).toHaveBeenCalledTimes(1);
    expect(onTranslate).not.toHaveBeenCalled();
  });

  it("shows exactly one speech language at a time", () => {
    renderEnglish(
      <TranscriptHistory transcript={transcript} showTranslated={true} />,
    );
    expect(
      screen.getByText(
        "【测试中文表示，不代表翻译质量】 Authoritative English speech.",
        { exact: false },
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/Test translation/)).toBeNull();
  });

  it("keeps the translation action usable while a batch is pending and labels test quality", () => {
    const pending = { ...batch, status: "pending" as const, failed_items: 0 };
    renderEnglish(
      <TranslationPanel batches={[pending]} onTranslate={() => undefined} />,
    );
    const panel = screen.getByRole("region", { name: "Test translation" });
    expect(within(panel).getByText("Mock test representation")).toBeTruthy();
    expect(within(panel).getByRole("button")).toBeTruthy();
  });
});
