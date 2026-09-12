import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  buildMockPersonaResponsePair,
  PersonaPreview,
  diffPersonaSpec,
  type PersonaPreviewSpec,
} from "../components/persona";

const first: PersonaPreviewSpec = {
  schema_version: "persona_spec_v1",
  identity: {
    name: "River Keeper",
    role: "Watershed steward",
    historical_or_cultural_context: "A fictional community keeper.",
  },
  cultural_lens: ["Intergenerational responsibility"],
  core_values: ["Reciprocity"],
  initial_position: "Protect shared resources.",
  speaking_style: {
    tone: "Calm",
    argument_pattern: "Context then consequences",
    concession_style: "Acknowledge valid concerns",
    question_style: "Ask about long-term effects",
  },
  debate_strategy: ["Connect present choices to future stewardship"],
  boundaries: ["Do not invent evidence"],
};

const second: PersonaPreviewSpec = {
  ...first,
  identity: { ...first.identity, name: "Market Steward" },
  core_values: ["Adaptability"],
  speaking_style: {
    tone: "Direct",
    argument_pattern: "Compare options then test",
    concession_style: "Adapt the proposal",
    question_style: "Ask about measurable results",
  },
  debate_strategy: ["Turn disagreement into an experiment"],
};

describe("Wave 4 structured Persona student preview", () => {
  afterEach(() => cleanup());

  it("computes the six teaching dimensions without treating identity/evidence as a dimension", () => {
    const diff = diffPersonaSpec(first, second);
    expect(diff).toHaveLength(6);
    expect(diff.filter((item) => item.changed).map((item) => item.key)).toEqual(
      [
        "tone",
        "value_priority",
        "argument_pattern",
        "concession_style",
        "question_style",
        "debate_strategy",
      ],
    );
  });

  it("shows structured fields and version diff without explanatory boilerplate", () => {
    render(
      <PersonaPreview
        rawAgentMd="# River Keeper"
        spec={second}
        previousSpec={first}
        confirmed
      />,
    );
    expect(screen.getByTestId("persona-preview")).toBeTruthy();
    expect(screen.getByText("Confirmed")).toBeTruthy();
    expect(screen.getByText("Direct")).toBeTruthy();
    expect(screen.queryByText(/KnowledgeSnapshot and evidence IDs/)).toBeNull();
    expect(screen.getAllByText(/Tone/)).not.toHaveLength(0);
    expect(screen.getByText(/Calm → Direct/)).toBeTruthy();
    expect(screen.getByText("Source")).toBeTruthy();
    expect(screen.getByTestId("persona-mock-response-pair")).toBeTruthy();
    expect(screen.getByText("Same-input Mock response pair")).toBeTruthy();
    expect(screen.getAllByText(/evidence: none/)).not.toHaveLength(0);
  });

  it("keeps the same Mock input while exposing Persona-driven response differences", () => {
    const pair = buildMockPersonaResponsePair(first, second, {
      evidenceIds: ["receipt-a", "receipt-b"],
      seed: 7,
    });
    expect(pair.first.evidence_ids).toEqual(pair.second.evidence_ids);
    expect(pair.first.rule_set_id).toBe(pair.second.rule_set_id);
    expect(pair.first.schema_version).toBe(pair.second.schema_version);
    expect(pair.first.seed).toBe(pair.second.seed);
    expect(pair.first.speech).not.toBe(pair.second.speech);
    expect(pair.first.teaching_dimensions.tone).not.toBe(
      pair.second.teaching_dimensions.tone,
    );
  });

  it("keeps an uncompiled draft explicit and never invents a default Persona", () => {
    render(<PersonaPreview rawAgentMd="# River Keeper" />);
    expect(screen.getByText("Pending")).toBeTruthy();
    expect(
      screen.getByText(/no default Persona or legacy fallback/),
    ).toBeTruthy();
    expect(screen.getByText("Source")).toBeTruthy();
  });
});
