import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fixtures = vi.hoisted(() => ({
  demoStatus: vi.fn(),
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({ api: { demoStatus: fixtures.demoStatus } }),
}));

import { DemoCompositionBadge } from "../components/demo-composition";
import { LocaleProvider } from "../components/locale";

afterEach(() => {
  cleanup();
  fixtures.demoStatus.mockReset();
});

describe("Real-Core Demo composition badge", () => {
  it("shows backend component modes and the published Bowen baseline", async () => {
    fixtures.demoStatus.mockResolvedValue({
      baseline: {
        agent_id: "9f6c9dc8-b4bf-5f9f-98d2-f8e718c1ce0b",
        version_id: "a7efcb9b-21fb-5d09-9366-3cc44b777d01",
        snapshot_id: "2572c3ac-4a1b-5bd8-a14a-a194ae7d3c6e",
        group_id: "66ee37fb-5772-5c8f-bb63-46d1783c53ae",
        system_baseline: true,
        immutable: true,
        usable: true,
      },
      composition: {
        components: [
          { key: "embedding", label: "Embedding", mode: "real" },
          { key: "llm", label: "Debate LLM", mode: "real" },
          { key: "tts", label: "TTS", mode: "mock" },
          { key: "voice", label: "Voice", mode: "mock" },
          { key: "translation", label: "Translation", mode: "mock" },
          { key: "report", label: "Maya Report", mode: "mock" },
        ],
      },
      dirty_agents: 0,
      dirty_debates: 0,
      dirty_interactions: 0,
    });

    render(
      <LocaleProvider initialLocale="en">
        <DemoCompositionBadge />
      </LocaleProvider>,
    );

    await screen.findByTestId("demo-composition");
    expect(screen.getByText("Published Demo Agent")).toBeTruthy();
    expect(screen.getByText("Bowen baseline ready")).toBeTruthy();
    expect(screen.getByText("System baseline")).toBeTruthy();
    expect(screen.getByTestId("demo-composition").textContent).toContain(
      "Embedding",
    );
    expect(
      document.querySelector(
        '[data-demo-component="embedding"] [data-demo-mode="real"]',
      ),
    ).toBeTruthy();
    expect(
      document.querySelector(
        '[data-demo-component="llm"] [data-demo-mode="real"]',
      ),
    ).toBeTruthy();
    for (const key of ["tts", "voice", "translation", "report"]) {
      expect(
        document.querySelector(
          `[data-demo-component="${key}"] [data-demo-mode="mock"]`,
        ),
      ).toBeTruthy();
    }
  });

  it("keeps the strip absent for an older session double without demo status", async () => {
    fixtures.demoStatus.mockRejectedValue(new Error("not available"));

    render(
      <LocaleProvider initialLocale="zh">
        <DemoCompositionBadge />
      </LocaleProvider>,
    );

    await waitFor(() =>
      expect(screen.queryByTestId("demo-composition")).toBeNull(),
    );
  });
});
