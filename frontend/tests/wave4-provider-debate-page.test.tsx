import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fixtures = vi.hoisted(() => ({
  debateId: "debate-approval-1",
  response: {
    debate_id: "debate-approval-1",
    items: [
      {
        turn_id: "turn-1",
        manifest_hash: "a".repeat(64),
        confirmation_revision: 1,
        confirmed: false,
      },
      {
        turn_id: "turn-2",
        manifest_hash: "b".repeat(64),
        confirmation_revision: 2,
        confirmed: true,
      },
    ],
  },
  list: vi.fn(),
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: {
      listProviderDataCallDebateManifests: fixtures.list,
    },
  }),
}));

import { TeacherProviderDataCallDebatePage } from "../components/provider";

afterEach(() => {
  cleanup();
  fixtures.list.mockReset();
  vi.unstubAllGlobals();
});

describe("teacher debate turn approval route controller", () => {
  it("loads each turn and links every status to its exact disclosure", async () => {
    fixtures.list.mockResolvedValue(fixtures.response);

    render(<TeacherProviderDataCallDebatePage debateId={fixtures.debateId} />);

    await screen.findByText("Debate turn approvals");
    expect(fixtures.list).toHaveBeenCalledWith(fixtures.debateId);
    expect(screen.getByText("turn-1")).toBeTruthy();
    expect(screen.getByText("turn-2")).toBeTruthy();
    expect(screen.getByText("Needs confirmation")).toBeTruthy();
    expect(screen.getByText("Confirmed")).toBeTruthy();

    const links = screen.getAllByRole("link", {
      name: "Review exact disclosure",
    });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      `/teacher/provider-disclosures/${fixtures.response.items[0].manifest_hash}`,
      `/teacher/provider-disclosures/${fixtures.response.items[1].manifest_hash}`,
    ]);
    expect(document.body.textContent).not.toMatch(
      /provider|model|endpoint|policy|prompt|usage/i,
    );
  });

  it("renders a safe empty state", async () => {
    fixtures.list.mockResolvedValue({
      debate_id: fixtures.debateId,
      items: [],
    });

    render(<TeacherProviderDataCallDebatePage debateId={fixtures.debateId} />);

    expect(
      await screen.findByText("No turn disclosure is waiting for review."),
    ).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("keeps a failed load recoverable through retry", async () => {
    fixtures.list
      .mockRejectedValueOnce(new Error("private backend detail"))
      .mockResolvedValueOnce(fixtures.response);

    render(<TeacherProviderDataCallDebatePage debateId={fixtures.debateId} />);

    await screen.findByRole("alert");
    expect(
      screen.getByText("Debate turn approvals could not be loaded."),
    ).toBeTruthy();
    expect(screen.queryByText("private backend detail")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(fixtures.list).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Debate turn approvals")).toBeTruthy();
  });
});

describe("PlatformApi debate approval endpoint", () => {
  it("uses the encoded debate path and returns only the safe DTO", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(fixtures.response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { PlatformApi } = await import("../lib/api/platform");
    const api = new PlatformApi({
      baseUrl: "https://maya.test/api/v1",
      csrfToken: "csrf-token",
    });
    const value = await api.listProviderDataCallDebateManifests("debate/1");

    expect(value).toEqual(fixtures.response);
    expect(fetchMock).toHaveBeenCalledWith(
      "https://maya.test/api/v1/provider/data-call/pending/debates/debate%2F1",
      {
        method: "GET",
        credentials: "include",
        headers: { "X-CSRF-Token": "csrf-token" },
      },
    );
  });
});
