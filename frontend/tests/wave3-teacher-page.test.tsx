import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TeacherWave3 } from "../components/wave3";
import type { DebateDetail, PlatformApi } from "../lib/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

class TeacherPageSocket {
  static instances: TeacherPageSocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  close = vi.fn();

  constructor(readonly url: string) {
    TeacherPageSocket.instances.push(this);
  }

  emitError(): void {
    this.onerror?.(new Event("error"));
  }

  emitClose(code: number): void {
    this.onclose?.({ code } as CloseEvent);
  }
}

function finishedDetail(): DebateDetail {
  return {
    id: "20000000-0000-4000-8000-000000000001",
    course_id: "10000000-0000-4000-8000-000000000001",
    topic: "Should classrooms compare cultural perspectives?",
    background: "",
    status: "completed",
    created_at: "2026-08-30T00:00:00Z",
    audio_restore_needed: false,
    prepared_turns: 0,
    expected_turns: 0,
    preview: null,
    output_language: "en",
    turn_protocol: null,
    preview_turns: [],
    final_input_frozen: false,
    stall: null,
    revision: 1,
    last_sequence: 1,
    rule_set_id: "ordered_multi_agent_rounds_demo_v1",
    round_count: 2,
    participants: [],
    public_turns: [],
    playback: {
      status: "completed",
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
  };
}

function teacherPageApi() {
  return {
    teacherInteraction: vi.fn().mockResolvedValue(null),
    debateTranscript: vi.fn().mockResolvedValue(null),
    getCurrentReport: vi.fn().mockResolvedValue(null),
    listReportRevisions: vi.fn().mockResolvedValue([]),
    listTranslationBatches: vi.fn().mockResolvedValue([]),
    regenerateReport: vi.fn(),
    getReportRevision: vi.fn(),
    downloadCurrentReport: vi.fn(),
  };
}

describe("Wave 3 dedicated teacher page", () => {
  it("restores Agent scores for the segments protocol", async () => {
    const detail = {
      ...finishedDetail(),
      turn_protocol: "segments_v2" as const,
    };
    const api = teacherPageApi();
    render(
      <TeacherWave3
        api={api as unknown as PlatformApi}
        debateId={detail.id}
        detail={detail}
      />,
    );

    await screen.findByText("Report");
    expect(screen.getByRole("heading", { name: "Scores" })).toBeTruthy();
    expect(screen.getByText("Direct evidence +5")).toBeTruthy();
    expect(screen.getByText("Indirect evidence +2")).toBeTruthy();
    expect(screen.getByText("No match +0")).toBeTruthy();
  });

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
      background: "",
      status: "stopped",
      created_at: "2026-08-30T00:00:00Z",
      audio_restore_needed: false,
      prepared_turns: 0,
      expected_turns: 0,
      preview: null,
      output_language: "en",
      turn_protocol: null,
      preview_turns: [],
      final_input_frozen: false,
      stall: null,
      revision: 1,
      last_sequence: 1,
      rule_set_id: "ordered_multi_agent_rounds_demo_v1",
      round_count: 2,
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

  it.each([
    [4401, "session_expired", "Your login has expired. Please sign in again."],
    [
      4403,
      "origin_mismatch",
      "The classroom address does not match the server configuration.",
    ],
  ])(
    "maps close code %s on the interaction/report page without Reconnect",
    async (code, reason, copy) => {
      TeacherPageSocket.instances = [];
      vi.stubGlobal("WebSocket", TeacherPageSocket);
      const detail = finishedDetail();
      const api = teacherPageApi();
      const { container } = render(
        <TeacherWave3
          api={api as unknown as PlatformApi}
          debateId={detail.id}
          detail={detail}
        />,
      );

      await waitFor(() => expect(TeacherPageSocket.instances).toHaveLength(1));
      TeacherPageSocket.instances[0]?.emitError();
      TeacherPageSocket.instances[0]?.emitClose(code);

      await screen.findByText(new RegExp(copy));
      expect(
        container.querySelector(`[data-wave3-connection-reason="${reason}"]`),
      ).toBeTruthy();
      expect(screen.queryByRole("button", { name: /Reconnect/ })).toBeNull();
    },
  );

  it("makes one explicit Wave 3 network recovery attempt", async () => {
    TeacherPageSocket.instances = [];
    vi.stubGlobal("WebSocket", TeacherPageSocket);
    const detail = finishedDetail();
    const api = teacherPageApi();
    render(
      <TeacherWave3
        api={api as unknown as PlatformApi}
        debateId={detail.id}
        detail={detail}
      />,
    );

    await waitFor(() => expect(TeacherPageSocket.instances).toHaveLength(1));
    await waitFor(() =>
      expect(api.teacherInteraction).toHaveBeenCalledTimes(1),
    );
    TeacherPageSocket.instances[0]?.emitClose(1006);
    await screen.findByText(/unconnected/);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(TeacherPageSocket.instances).toHaveLength(1);
    expect(api.teacherInteraction).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /Reconnect/ }));
    await waitFor(() => expect(TeacherPageSocket.instances).toHaveLength(2));
    await waitFor(() =>
      expect(api.teacherInteraction).toHaveBeenCalledTimes(2),
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(TeacherPageSocket.instances).toHaveLength(2);
    expect(api.teacherInteraction).toHaveBeenCalledTimes(2);
  });
});
