import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "../components/locale";
import {
  ReportPanel,
  type Report,
  type ReportPanelApi,
  type ReportRevision,
} from "../components/report";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const debateId = "11111111-1111-4111-8111-111111111111";
const revisionId = "22222222-2222-4222-8222-222222222222";

function readyReport(markdown = "# Civilization Mutual Learning Report") {
  return {
    debate_id: debateId,
    generation_status: "ready",
    latest_attempt_status: "ready",
    insight: {
      status: "ready",
      included_count: 2,
      filtered_count: 1,
      items: [{ category: "support", summary: "Shared concern", count: 2 }],
    },
    active_revision_id: null,
    current_success_revision: {
      id: revisionId,
      revision_no: 1,
      status: "ready",
      english_markdown: markdown,
      word_count: 640,
      safe_error_code: null,
      created_at: "2026-08-29T00:00:00Z",
    },
  } as Report;
}

function revisions(): ReportRevision[] {
  return [
    {
      id: revisionId,
      revision_no: 1,
      status: "ready",
      english_markdown: "# Civilization Mutual Learning Report\n\nplain",
      word_count: 640,
      safe_error_code: null,
      created_at: "2026-08-29T00:00:00Z",
    },
  ];
}

function apiMock(overrides: Partial<ReportPanelApi> = {}): ReportPanelApi {
  return {
    getCurrentReport: vi.fn(async () => readyReport()),
    regenerateReport: vi.fn(async () => readyReport()),
    listReportRevisions: vi.fn(async () => revisions()),
    getReportRevision: vi.fn(async () => revisions()[0]),
    downloadCurrentReport: vi.fn(async () => ({
      content: "# report",
      filename: "report.md",
    })),
    ...overrides,
  };
}

describe("Wave 3 M14 ReportPanel", () => {
  it("offers only Regenerate even before the first report", async () => {
    const api = apiMock({
      getCurrentReport: vi.fn(
        async () =>
          ({
            ...readyReport(),
            generation_status: "not_started",
            latest_attempt_status: "not_started",
            current_success_revision: null,
          }) as Report,
      ),
      listReportRevisions: vi.fn(async () => []),
    });
    render(
      <LocaleProvider initialLocale="en">
        <ReportPanel debateId={debateId} api={api} />
      </LocaleProvider>,
    );

    await screen.findByText("Report");
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Generate Report" }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Regenerate" })).toBeTruthy();
  });

  it("allows Regenerate while insight preparation is still running", async () => {
    const api = apiMock({
      getCurrentReport: vi.fn(
        async () =>
          ({
            ...readyReport(),
            generation_status: "not_started",
            latest_attempt_status: "not_started",
            insight: { ...readyReport().insight, status: "generating" },
            current_success_revision: null,
          }) as Report,
      ),
      listReportRevisions: vi.fn(async () => []),
    });
    render(
      <LocaleProvider initialLocale="en">
        <ReportPanel debateId={debateId} api={api} />
      </LocaleProvider>,
    );

    await screen.findByText("Report");
    const button = screen.getByRole("button", { name: "Regenerate" });
    expect(button).toHaveProperty("disabled", false);
    fireEvent.click(button);
    await waitFor(() =>
      expect(api.regenerateReport).toHaveBeenCalledWith(
        debateId,
        expect.objectContaining({ idempotency: expect.anything() }),
      ),
    );
  });

  it("polls a generating report until the authoritative status is ready", async () => {
    vi.useFakeTimers();
    const generating = {
      ...readyReport(),
      generation_status: "generating",
      latest_attempt_status: "generating",
      insight: { ...readyReport().insight, status: "generating" },
      current_success_revision: null,
    } as Report;
    const ready = readyReport("# Civilization Mutual Learning Report\n\nready");
    const getCurrentReport = vi
      .fn<ReportPanelApi["getCurrentReport"]>()
      .mockResolvedValueOnce(generating)
      .mockResolvedValueOnce(ready);
    const api = apiMock({
      getCurrentReport,
      listReportRevisions: vi
        .fn()
        .mockResolvedValueOnce([])
        .mockResolvedValueOnce(revisions()),
    });
    render(
      <LocaleProvider initialLocale="en">
        <ReportPanel debateId={debateId} api={api} />
      </LocaleProvider>,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText("Generating report…")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(screen.getByText(/ready/)).toBeTruthy();
    expect(getCurrentReport).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it("removes status chrome while preserving insight content and report text", async () => {
    const api = apiMock();
    render(
      <LocaleProvider initialLocale="en">
        <ReportPanel debateId={debateId} api={api} />
      </LocaleProvider>,
    );

    expect(await screen.findByText("Report")).toBeTruthy();
    expect(screen.getByText("Shared concern")).toBeTruthy();
    expect(screen.queryByText("Anonymous classroom insight")).toBeNull();
    expect(screen.queryByText("Current report")).toBeNull();
    expect(screen.queryByText(/included.*filtered/)).toBeNull();
    expect(screen.getByLabelText("Current report").textContent).toContain(
      "Civilization Mutual Learning Report",
    );
  });

  it.each(["ready", "failed"] as const)(
    "renders terminal %s status despite a failed revision-history request",
    async (status) => {
      vi.useFakeTimers();
      const generating = {
        ...readyReport(),
        generation_status: "generating",
        latest_attempt_status: "generating",
        current_success_revision: null,
      } as Report;
      const terminal = {
        ...readyReport(),
        generation_status: status,
        latest_attempt_status: status,
      } as Report;
      const getCurrentReport = vi
        .fn<ReportPanelApi["getCurrentReport"]>()
        .mockResolvedValueOnce(generating)
        .mockResolvedValue(terminal);
      const api = apiMock({
        getCurrentReport,
        listReportRevisions: vi
          .fn()
          .mockRejectedValue(new Error("History unavailable")),
      });
      render(
        <LocaleProvider initialLocale="en">
          <ReportPanel debateId={debateId} api={api} />
        </LocaleProvider>,
      );

      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByText("Generating report…")).toBeTruthy();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1500);
      });
      expect(screen.queryByText("Generating report…")).toBeNull();
      expect(screen.getByLabelText("Current report").textContent).toContain(
        "Civilization Mutual Learning Report",
      );
      if (status === "failed") {
        expect(
          screen.getByText(
            "Report generation failed; earlier revisions remain.",
          ),
        ).toBeTruthy();
      }
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3000);
      });
      expect(getCurrentReport).toHaveBeenCalledTimes(2);
      expect(api.regenerateReport).not.toHaveBeenCalled();
    },
  );

  it("keeps polling status while revision history is pending", async () => {
    vi.useFakeTimers();
    const getCurrentReport = vi
      .fn<ReportPanelApi["getCurrentReport"]>()
      .mockResolvedValueOnce({
        ...readyReport(),
        generation_status: "generating",
        latest_attempt_status: "generating",
        current_success_revision: null,
      } as Report)
      .mockResolvedValue(readyReport());
    const api = apiMock({
      getCurrentReport,
      listReportRevisions: vi.fn<ReportPanelApi["listReportRevisions"]>(
        () => new Promise(() => {}),
      ),
    });
    render(
      <LocaleProvider initialLocale="en">
        <ReportPanel debateId={debateId} api={api} />
      </LocaleProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText("Generating report…")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(screen.queryByText("Generating report…")).toBeNull();
    expect(screen.getByLabelText("Current report")).toBeTruthy();
    expect(getCurrentReport).toHaveBeenCalledTimes(2);
    expect(api.regenerateReport).not.toHaveBeenCalled();
  });

  it("does not let an older poll replace a ready report after updated panel inputs", async () => {
    vi.useFakeTimers();
    const generating = {
      ...readyReport(),
      generation_status: "generating",
      latest_attempt_status: "generating",
      current_success_revision: null,
    } as Report;
    let resolveOldPoll!: (value: Report) => void;
    const oldPoll = new Promise<Report>((resolve) => {
      resolveOldPoll = resolve;
    });
    const getCurrentReport = vi
      .fn<ReportPanelApi["getCurrentReport"]>()
      .mockResolvedValueOnce(generating)
      .mockReturnValueOnce(oldPoll)
      .mockResolvedValue(readyReport());
    const api = apiMock({ getCurrentReport });
    const { rerender } = render(
      <LocaleProvider initialLocale="en">
        <ReportPanel debateId={debateId} api={api} />
      </LocaleProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    await act(async () => {
      rerender(
        <LocaleProvider initialLocale="en">
          <ReportPanel debateId={debateId} api={{ ...api }} />
        </LocaleProvider>,
      );
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByLabelText("Current report")).toBeTruthy();
    await act(async () => {
      resolveOldPoll(generating);
    });
    expect(screen.queryByText("Generating report…")).toBeNull();
    expect(screen.getByLabelText("Current report")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(getCurrentReport).toHaveBeenCalledTimes(3);
    expect(api.regenerateReport).not.toHaveBeenCalled();
  });

  it("regenerates through the platform adapter and reloads status", async () => {
    const regenerated = readyReport(
      "# Civilization Mutual Learning Report\n\nupdated",
    );
    const api = apiMock({
      regenerateReport: vi.fn(async () => regenerated),
      getCurrentReport: vi
        .fn()
        .mockResolvedValueOnce(readyReport())
        .mockResolvedValueOnce(regenerated),
    });
    render(
      <LocaleProvider initialLocale="en">
        <ReportPanel debateId={debateId} api={api} />
      </LocaleProvider>,
    );
    await screen.findByText("Report");
    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    await waitFor(() =>
      expect(api.regenerateReport).toHaveBeenCalledWith(
        debateId,
        expect.objectContaining({ idempotency: expect.anything() }),
      ),
    );
    expect(await screen.findByText(/updated/)).toBeTruthy();
  });

  it("reuses one idempotency handle after an ambiguous regenerate failure", async () => {
    const regenerateReport = vi
      .fn()
      .mockRejectedValueOnce(new Error("network interrupted"))
      .mockResolvedValueOnce(readyReport());
    const api = apiMock({ regenerateReport });
    render(
      <LocaleProvider initialLocale="en">
        <ReportPanel debateId={debateId} api={api} />
      </LocaleProvider>,
    );
    await screen.findByText("Report");
    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    await waitFor(() => expect(regenerateReport).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    await waitFor(() => expect(regenerateReport).toHaveBeenCalledTimes(2));
    expect(regenerateReport.mock.calls[0][1]?.idempotency).toBe(
      regenerateReport.mock.calls[1][1]?.idempotency,
    );
  });

  it("downloads only current success and hides download for selected history", async () => {
    const api = apiMock();
    const createObjectURL = vi.fn(() => "blob:test");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    render(
      <LocaleProvider initialLocale="en">
        <ReportPanel debateId={debateId} api={api} />
      </LocaleProvider>,
    );
    await screen.findByText("Report");
    fireEvent.click(screen.getByRole("button", { name: "Download Markdown" }));
    await waitFor(() =>
      expect(api.downloadCurrentReport).toHaveBeenCalledWith(debateId, "en"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() =>
      expect(api.getReportRevision).toHaveBeenCalledWith(debateId, revisionId),
    );
    expect(
      screen.queryByRole("button", { name: "Download Markdown" }),
    ).toBeNull();
  });
});
