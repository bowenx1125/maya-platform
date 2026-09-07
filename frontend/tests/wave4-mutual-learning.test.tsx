import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  DebateDetail,
  DebateCreateController,
} from "../components/debate/setup/debate-setup";
import { TeacherDebateCreate } from "../components/debate/setup/debate-setup";
import {
  phaseLabel,
  resolveDebateRoundPhase,
} from "../components/debate/stage/labels";
import type { PublishedAgentSummary } from "../lib/api";

const useSessionMock = vi.hoisted(() => vi.fn());
const router = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("../components/session-provider", () => ({
  useSession: useSessionMock,
}));

const courseId = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b";
const mutualRuleSet = "ordered_multi_expert_mutual_learning_v1";

afterEach(() => {
  cleanup();
  router.replace.mockReset();
  useSessionMock.mockReset();
});

function candidate(id: string, name: string): PublishedAgentSummary {
  return {
    agent: {
      id,
      group_id: `${id}-group`,
      name,
      description: `${name} perspective`,
      status: "active",
      current_published_version_id: `${id}-version`,
      current_draft_version_id: null,
    },
    current_version: {
      id: `${id}-version`,
      agent_id: id,
      version_label: "V1.0",
      state: "published",
      revision: 1,
    },
  } as PublishedAgentSummary;
}

function setupController(
  create: ReturnType<typeof vi.fn>,
): DebateCreateController {
  return {
    loadCandidates: vi
      .fn()
      .mockResolvedValue([
        candidate("bowen", "Bowen"),
        candidate("kaikai", "Kaikai"),
      ]),
    create: create as unknown as DebateCreateController["create"],
  };
}

function createdDebate(): DebateDetail {
  return { id: "debate-id" } as DebateDetail;
}

function renderCreate(create = vi.fn().mockResolvedValue(createdDebate())) {
  useSessionMock.mockReturnValue({
    api: {},
    user: { courses: [{ course_id: courseId, role: "teacher" }] },
  });
  render(<TeacherDebateCreate controller={setupController(create)} />);
  return create;
}

describe("Wave 4 mutual-learning setup and phase view helpers", () => {
  it.each([
    ["en", "Should classrooms compare cultural perspectives?"],
    ["zh", "课堂如何比较不同文化的观点？"],
  ])("sends four rounds for %s debates", async (language, topic) => {
    const create = vi.fn().mockResolvedValue(createdDebate());
    renderCreate(create);
    await screen.findByRole("button", { name: /Bowen/ });
    fireEvent.click(screen.getByRole("button", { name: /Bowen/ }));
    fireEvent.click(screen.getByRole("button", { name: /Kaikai/ }));
    fireEvent.change(screen.getByLabelText("Language"), {
      target: { value: language },
    });
    fireEvent.change(screen.getByLabelText("Topic"), {
      target: { value: topic },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Create debate draft" }),
    );
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0]?.[1]).toMatchObject({
      rule_set_id: mutualRuleSet,
      round_count: 4,
      output_language: language,
    });
  });

  it("offers only mutual learning without a round-selection module", async () => {
    // The legacy demo RuleSets stay readable on existing Debates but can no
    // longer be created, so the setup surface has no protocol choice at all.
    renderCreate();
    await screen.findByRole("button", { name: /Bowen/ });
    expect(screen.queryByRole("option", { name: /legacy/i })).toBeNull();
    expect(screen.getByTestId("debate-rule-set")).toBeTruthy();
    expect(screen.queryByRole("radiogroup", { name: "Rounds" })).toBeNull();
    expect(screen.queryByText("Rounds")).toBeNull();
    expect(screen.queryByRole("radio")).toBeNull();
  });

  it("resolves opening, exchange, and final integration from explicit markers", () => {
    expect(resolveDebateRoundPhase(1, false)).toBe("opening");
    expect(resolveDebateRoundPhase(2, false)).toBe("exchange");
    expect(resolveDebateRoundPhase(2, true)).toBe("final_integration");
    expect(resolveDebateRoundPhase(5, true)).toBe("final_integration");
    expect(phaseLabel("final_integration")).toBe("Final integration");
  });
});
