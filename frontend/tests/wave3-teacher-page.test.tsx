import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TeacherWave3 } from "../components/wave3";
import type { DebateDetail, PlatformApi } from "../lib/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Wave 3 dedicated teacher page", () => {
  it("does not mount any downstream reader for a partial Finish", async () => {
    const methods = {
      teacherInteraction: vi.fn(),
      debateTranscript: vi.fn(),
      getCurrentReport: vi.fn(),
      listReportRevisions: vi.fn(),
      listTranslationBatches: vi.fn(),
    };
    const detail = {
      id: "20000000-0000-4000-8000-000000000001",
      course_id: "10000000-0000-4000-8000-000000000001",
      topic: "Should classrooms compare cultural perspectives?",
      status: "stopped",
      created_at: "2026-08-30T00:00:00Z",
      revision: 1,
      last_sequence: 1,
      rule_set_id: "ordered_multi_agent_rounds_demo_v1",
      participants: [],
      public_turns: [],
      playback: {
        status: "stopped",
        mode: "live",
        current_turn_id: null,
        cursor_ms: 0,
        playback_rate: 1,
        control_version: 1,
        next_turn_ready: false,
      },
      interaction_status: "closed",
      insight_status: "not_started",
      report_status: "not_started",
    } as DebateDetail;

    render(
      <TeacherWave3
        api={methods as unknown as PlatformApi}
        debateId={detail.id}
        detail={detail}
      />,
    );

    expect(
      screen.getByText(/Partial or unfinished debates keep generated turns/),
    ).toBeTruthy();
    await new Promise((resolve) => setTimeout(resolve, 10));
    for (const method of Object.values(methods)) {
      expect(method).not.toHaveBeenCalled();
    }
    expect(screen.queryByText(/Maya Civilization Mutual Learning/)).toBeNull();
  });
});
