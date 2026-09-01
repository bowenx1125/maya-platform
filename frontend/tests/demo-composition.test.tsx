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
        agent_id: "93c04441-1bae-54b2-8037-78622b88d640",
        version_id: "e792ee07-7f8b-52d2-817b-d315a3d32445",
        snapshot_id: "49985a15-9633-5190-9982-173c7a21d6e7",
        group_id: "7813f937-902c-5534-bfb2-ad773a43aeda",
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
