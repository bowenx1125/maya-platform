import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  buildMockPersonaResponse,
  buildPersonaTemplate,
  diffPersonaSpec,
  PersonaPreview,
  syncPersonaTemplateName,
  type PersonaPreviewSpec,
} from "../components/persona";

const current: PersonaPreviewSpec = {
  schema_version: "persona_spec_v2",
  identity: {
    name: "River Keeper",
    role: "Watershed steward",
    historical_or_cultural_context: "一个虚构的社区守护者。",
  },
  cultural_lens: ["代际责任"],
  core_values: ["Reciprocity"],
  initial_position: "保护共享资源。",
  speaking_style: {
    tone: "Calm and reflective",
    argument_pattern: "先说明背景，再权衡后果",
    concession_style: "Acknowledge valid concerns",
    question_style: "Ask one open question",
  },
};

describe("current five-section Persona helpers", () => {
  afterEach(() => cleanup());

  it("derives the H1 from the one supplied Agent name", () => {
    const template = buildPersonaTemplate("River Keeper");
    expect(template.startsWith("# River Keeper\n")).toBe(true);
    expect(template).toContain("## Speaking style");
    expect(template).not.toContain("## Debate strategy");
    expect(template).not.toContain("## Boundaries");
    expect(syncPersonaTemplateName(template, "Market Steward")).toContain(
      "# Market Steward\n",
    );
  });

  it("compares and renders only the five current sections", () => {
    expect(diffPersonaSpec(current, current)).toHaveLength(5);
    render(
      <PersonaPreview
        rawAgentMd={buildPersonaTemplate(current.identity.name)}
        spec={current}
        confirmed
      />,
    );
    expect(screen.getByTestId("persona-preview")).toBeTruthy();
    expect(screen.getByText("代际责任")).toBeTruthy();
    expect(screen.queryByText("Debate strategy")).toBeNull();
    expect(screen.queryByText("Boundaries")).toBeNull();
  });

  it("does not synthesize removed fields in the V2 Mock response", () => {
    const response = buildMockPersonaResponse(current, {
      topic: "How should a community share a scarce resource?",
      evidenceIds: [],
      stance: "open",
      seed: 7,
    });
    expect(response.teaching_dimensions).not.toHaveProperty("debate_strategy");
    expect(response.speech).not.toContain("debate strategy");
  });
});
