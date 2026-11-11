import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DebateDiagnosticsView } from "../components/debate/diagnostics";
import type { DebateDiagnostics } from "../lib/api/debate-diagnostics";
import { PlatformApiError } from "../lib/api";

const useSessionMock = vi.hoisted(() => vi.fn());
const fetchMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ debate_id: "20000000-0000-4000-8000-000000000001" }),
}));
vi.mock("../components/session-provider", () => ({
  RouteGuard: ({ children }: { children: ReactNode }) => children,
  useSession: useSessionMock,
}));
vi.mock("../components/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("../components/page-action", () => ({
  PageAction: ({ href }: { href?: string }) => (
    <a data-testid="back" href={href}>
      Back
    </a>
  ),
}));
vi.mock("../lib/api/debate-diagnostics", () => ({
  fetchDebateDiagnostics: fetchMock,
}));

import TeacherDebateDiagnosticsPage from "../app/teacher/debates/[debate_id]/diagnostics/page";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const v4: DebateDiagnostics = {
  debate_id: "20000000-0000-4000-8000-000000000001",
  output_language: "en",
  unit: "words",
  length_capped: true,
  agents: [
    {
      participant_id: "participant-a",
      agent_name: "River Keeper",
      slot: "A",
      agent_md_chars: 1240,
      knowledge_documents: 1,
      knowledge_chunks: 1,
      retrievals: 3,
      distinct_chunks: 1,
      cited_chunks: 1,
      traced_share: 0.083,
      grounding_counts: { quoted: 1, paraphrased: 0, not_found: 2 },
      rounds: [
        {
          turn_id: "turn-a1",
          round_no: 1,
          turn_index: 0,
          speech_units: 92,
          unit_cap: 85,
          repaired: true,
          traced_share: 0.31,
          repeats_earlier_share: null,
          retrieved: [
            {
              chunk_id: "chunk-1",
              source_filename: "water-sharing.md",
              rank: 1,
              score: 0.7876,
              chunk_chars: 4060,
              cited: true,
            },
          ],
          paragraphs: [
            {
              units: 60,
              cited_sources: 1,
              self_label: "direct",
              grounding_class: "quoted",
              coverage: 0.52,
              longest_run: 14,
            },
            {
              units: 32,
              cited_sources: 0,
              self_label: "no_match",
              grounding_class: null,
              coverage: null,
              longest_run: null,
            },
          ],
        },
        {
          turn_id: "turn-a2",
          round_no: 2,
          turn_index: 2,
          speech_units: 70,
          unit_cap: 70,
          repaired: false,
          traced_share: null,
          repeats_earlier_share: 0.12,
          retrieved: [],
          paragraphs: null,
        },
      ],
    },
    {
      participant_id: "participant-b",
      agent_name: "Market Steward",
      slot: "B",
      agent_md_chars: null,
      knowledge_documents: 3,
      knowledge_chunks: 14,
      retrievals: 0,
      distinct_chunks: 0,
      cited_chunks: 0,
      traced_share: null,
      grounding_counts: { quoted: 0, paraphrased: 0, not_found: 0 },
      rounds: [],
    },
  ],
};

describe("DebateDiagnosticsView", () => {
  it("shows each Agent's numbers at a glance and rounds on expand", () => {
    render(<DebateDiagnosticsView topic="Water" diagnostics={v4} />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Water · Diagnostics" }),
    ).toHaveProperty("dataset.uiGuideText");
    const river = screen.getByTestId("diagnostics-agent-participant-a");
    expect(within(river).getByText("Agent.md 1,240 chars")).toBeTruthy();
    expect(within(river).getByText("RAG 1 doc · 1 chunk")).toBeTruthy();
    expect(within(river).getByTestId("agent-retrieved").textContent).toContain(
      "Retrieved 1 distinct / 3 · same chunk every time",
    );
    expect(within(river).getByTestId("agent-traced").textContent).toContain(
      "Traced 8%",
    );
    expect(
      within(river).getByText("Quoted 1 · Paraphrased 0 · Not found 2"),
    ).toBeTruthy();
    // The per-round breakdown is folded until the teacher opens it.
    const details = within(river)
      .getByTestId("diagnostics-rounds")
      .closest("details");
    expect(details?.hasAttribute("open")).toBe(false);
    fireEvent.click(within(river).getByTestId("diagnostics-rounds"));
    expect(details?.hasAttribute("open")).toBe(true);
    const first = within(river).getByTestId("diagnostics-round-turn-a1");
    expect(within(first).getByText("Round 1 · Opening")).toBeTruthy();
    expect(within(first).getByText("92 / 85 words")).toBeTruthy();
    expect(within(first).getByText("Repaired")).toBeTruthy();
    expect(within(first).getByText("water-sharing.md")).toBeTruthy();
    expect(
      within(first).getByText("rank 1 · score 0.79 · 4,060 chars"),
    ).toBeTruthy();
    expect(within(first).getByText("Cited")).toBeTruthy();
    const paragraphs = within(first).getAllByTestId("diagnostics-paragraph");
    expect(paragraphs[0].textContent).toContain(
      "60 words · Model: Direct · Server: Quoted (52%)",
    );
    expect(paragraphs[1].textContent).toContain(
      "32 words · Model: No match · Server: no source cited",
    );
    const second = within(river).getByTestId("diagnostics-round-turn-a2");
    expect(within(second).getByText("Repeats earlier 12%")).toBeTruthy();
    expect(within(second).getByText("Nothing retrieved.")).toBeTruthy();
    expect(
      within(second).getByText("Paragraphs were not stored for this turn."),
    ).toBeTruthy();

    const market = screen.getByTestId("diagnostics-agent-participant-b");
    expect(within(market).getByText("Agent.md not kept")).toBeTruthy();
    expect(within(market).getByText("No generated speech yet.")).toBeTruthy();
    expect(within(market).getByTestId("agent-traced").textContent).toContain(
      "Traced —",
    );
  });

  it("shows speech length without a cap before v4 and in Han characters", () => {
    const preV4: DebateDiagnostics = {
      ...v4,
      unit: "han_chars",
      output_language: "zh",
      length_capped: false,
      agents: [
        {
          ...v4.agents[0],
          rounds: [{ ...v4.agents[0].rounds[0], unit_cap: null }],
        },
      ],
    };
    render(<DebateDiagnosticsView diagnostics={preV4} />);
    fireEvent.click(screen.getByTestId("diagnostics-rounds"));
    expect(screen.getByText("92 Han chars")).toBeTruthy();
    expect(
      screen.getByRole("heading", { level: 1, name: "Diagnostics" }),
    ).toBeTruthy();
  });

  it("has an empty state and a slot for a later per-Agent card", () => {
    const { unmount } = render(
      <DebateDiagnosticsView diagnostics={{ ...v4, agents: [] }} />,
    );
    expect(screen.getByText("No Agents in this Debate.")).toBeTruthy();
    unmount();
    render(
      <DebateDiagnosticsView
        diagnostics={v4}
        agentSlot={(agent) => <span>card for {agent.agent_name}</span>}
      />,
    );
    expect(screen.getByText("card for River Keeper")).toBeTruthy();
  });
});

describe("TeacherDebateDiagnosticsPage", () => {
  it("loads, then shows the view with Back to the Debate", async () => {
    let resolve: (value: DebateDiagnostics) => void = () => {};
    fetchMock.mockReturnValue(
      new Promise<DebateDiagnostics>((done) => {
        resolve = done;
      }),
    );
    useSessionMock.mockReturnValue({
      api: { debate: vi.fn().mockResolvedValue({ topic: "Water" }) },
    });
    render(<TeacherDebateDiagnosticsPage />);
    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.getByTestId("back").getAttribute("href")).toBe(
      "/teacher/debates/20000000-0000-4000-8000-000000000001/control",
    );
    resolve(v4);
    await waitFor(() =>
      expect(screen.getByTestId("debate-diagnostics")).toBeTruthy(),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "20000000-0000-4000-8000-000000000001",
    );
  });

  it("names a missing Debate instead of a generic failure", async () => {
    fetchMock.mockRejectedValue(
      new PlatformApiError(404, "Not found", {
        code: "not_found",
        message: "Not found",
      }),
    );
    useSessionMock.mockReturnValue({
      api: { debate: vi.fn().mockResolvedValue({ topic: "Water" }) },
    });
    render(<TeacherDebateDiagnosticsPage />);
    expect(
      await screen.findByText(
        "This Debate was deleted or is no longer available to you.",
      ),
    ).toBeTruthy();
    expect(screen.queryByTestId("debate-diagnostics")).toBeNull();
  });
});
