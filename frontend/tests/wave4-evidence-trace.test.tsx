import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  EvidenceTraceInspector,
  normaliseEvidenceTrace,
  speechSpanText,
  type EvidenceTraceRow,
} from "../components/evidence";

afterEach(() => cleanup());

const speech = "Opening 😀 claim: communities need care.";
const claim = "claim: communities need care.";

const directTrace: EvidenceTraceRow = {
  trace_version: "evidence_trace_v1",
  turn_id: "turn-a",
  claim_id: "claim-a",
  claim_text: claim,
  claim_type: "factual",
  query_id: "query-a",
  query_kind: "viewpoint",
  query_text: "Find the community claim.",
  evidence_id: "evidence-a",
  chunk_id: "chunk-a",
  source_filename: "community.md",
  source_locator: "md:document-a:chars:0-32",
  support_mode: "direct",
  speech_span: { start_utf16: 11, end_utf16: 40 },
};

function renderEnglish(children: React.ReactNode) {
  return render(<>{children}</>);
}

describe("Wave 4 EvidenceTrace teaching inspector", () => {
  it("uses UTF-16 half-open spans to highlight the exact speech claim", () => {
    expect(speechSpanText(speech, directTrace.speech_span)).toBe(claim);
    expect(normaliseEvidenceTrace([directTrace])).toEqual([directTrace]);

    renderEnglish(
      <EvidenceTraceInspector speech={speech} trace={[directTrace]} />,
    );
    fireEvent.click(screen.getByText("Check RAG", { exact: false }));
    expect(screen.getByText(claim)).toBeTruthy();
    expect(screen.getByText("community.md")).toBeTruthy();
    expect(screen.getByText("md:document-a:chars:0-32")).toBeTruthy();
    // The grade states what it is worth, so the panel needs no sentence
    // underneath explaining that a lineage record is not a fact check.
    expect(screen.getByText("Direct evidence")).toBeTruthy();
    expect(screen.getByText("+5")).toBeTruthy();
    expect(screen.queryByText(/verified true|fact-checked/i)).toBeNull();
  });

  it("does not render private source fields for general reasoning or no-match", () => {
    const noMatch: EvidenceTraceRow = {
      ...directTrace,
      claim_id: "claim-no-match",
      claim_text: speech,
      claim_type: "proposal",
      query_id: null,
      query_kind: null,
      query_text: null,
      evidence_id: null,
      chunk_id: null,
      source_filename: null,
      source_locator: null,
      support_mode: "no_match",
      speech_span: { start_utf16: 0, end_utf16: speech.length },
    };
    renderEnglish(<EvidenceTraceInspector speech={speech} trace={[noMatch]} />);
    expect(screen.getByText("No evidence")).toBeTruthy();
    expect(screen.queryByText("community.md")).toBeNull();
    expect(screen.queryByText(/md:document-a/)).toBeNull();
  });
});
