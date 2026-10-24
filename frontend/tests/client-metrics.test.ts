import { afterEach, describe, expect, it, vi } from "vitest";

import {
  flushClientMetrics,
  markDebateNextClicked,
  noteDebateSpeechPlaying,
  pageTemplate,
  recordClientMetric,
  resetClientMetricsForTests,
  setClientMetricsTransport,
} from "../lib/client-metrics";

afterEach(() => {
  vi.useRealTimers();
  resetClientMetricsForTests(false);
});

describe("client metrics", () => {
  it("folds record ids out of the page path", () => {
    expect(
      pageTemplate(
        "/teacher/debates/3f2b1c4d-0000-4000-8000-123456789abc/stage",
      ),
    ).toBe("/teacher/debates/{id}/stage");
    expect(pageTemplate("/student/chats/12345")).toBe("/student/chats/{id}");
    expect(pageTemplate("/teacher")).toBe("/teacher");
  });

  it("records nothing when this page load is not sampled", () => {
    const transport = vi.fn(() => Promise.resolve());
    setClientMetricsTransport(transport);
    recordClientMetric("page_first_render", 120);
    flushClientMetrics();
    expect(transport).not.toHaveBeenCalled();
  });

  it("batches sampled metrics and sends them after the flush interval", () => {
    vi.useFakeTimers();
    resetClientMetricsForTests(true);
    const transport = vi.fn(() => Promise.resolve());
    setClientMetricsTransport(transport);
    recordClientMetric("page_first_render", 120.4);
    recordClientMetric("assessment_submit", 900);
    expect(transport).not.toHaveBeenCalled();
    vi.advanceTimersByTime(30_000);
    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport).toHaveBeenCalledWith([
      expect.objectContaining({ name: "page_first_render", ms: 120 }),
      expect.objectContaining({ name: "assessment_submit", ms: 900 }),
    ]);
  });

  it("holds metrics until a signed-in transport exists", () => {
    resetClientMetricsForTests(true);
    recordClientMetric("page_first_render", 50);
    flushClientMetrics();
    const transport = vi.fn(() => Promise.resolve());
    setClientMetricsTransport(transport);
    expect(transport).toHaveBeenCalledTimes(1);
  });

  it("times Next to the next speech and ignores a stale click", () => {
    resetClientMetricsForTests(true);
    const transport = vi.fn(() => Promise.resolve());
    setClientMetricsTransport(transport);
    const now = vi.spyOn(performance, "now");
    now.mockReturnValue(1_000);
    markDebateNextClicked();
    now.mockReturnValue(1_750);
    noteDebateSpeechPlaying();
    now.mockReturnValue(5_000);
    markDebateNextClicked();
    now.mockReturnValue(5_000 + 130_000);
    noteDebateSpeechPlaying();
    flushClientMetrics();
    now.mockRestore();
    expect(transport).toHaveBeenCalledWith([
      expect.objectContaining({ name: "debate_next_to_play", ms: 750 }),
    ]);
  });

  it("drops a failed send without throwing", () => {
    resetClientMetricsForTests(true);
    setClientMetricsTransport(() => {
      throw new Error("offline");
    });
    recordClientMetric("page_first_render", 10);
    expect(() => flushClientMetrics()).not.toThrow();
  });
});
