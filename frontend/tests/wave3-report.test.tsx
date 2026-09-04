import {
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

afterEach(() => cleanup());

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
  it("shows insight/report state and renders Markdown as text", async () => {
    const api = apiMock();
    render(
      <LocaleProvider initialLocale="en">
        <ReportPanel debateId={debateId} api={api} />
      </LocaleProvider>,
    );

    expect(
      await screen.findByText("Turn the debate into a shared learning record"),
    ).toBeTruthy();
    expect(screen.getByText("Shared concern")).toBeTruthy();
    expect(screen.getByLabelText("Current report").textContent).toContain(
      "Civilization Mutual Learning Report",
    );
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
    await screen.findByText("Turn the debate into a shared learning record");
    fireEvent.click(screen.getByRole("button", { name: "Regenerate report" }));
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
    await screen.findByText("Turn the debate into a shared learning record");
    fireEvent.click(screen.getByRole("button", { name: "Regenerate report" }));
    await waitFor(() => expect(regenerateReport).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Regenerate report" }));
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
    await screen.findByText("Turn the debate into a shared learning record");
    fireEvent.click(
      screen.getByRole("button", { name: "Download English Markdown" }),
    );
    await waitFor(() =>
      expect(api.downloadCurrentReport).toHaveBeenCalledWith(debateId, "en"),
    );
    fireEvent.click(screen.getByRole("button", { name: "View revision" }));
    await waitFor(() =>
      expect(api.getReportRevision).toHaveBeenCalledWith(debateId, revisionId),
    );
    expect(
      screen.queryByRole("button", { name: "Download English Markdown" }),
    ).toBeNull();
  });
});
