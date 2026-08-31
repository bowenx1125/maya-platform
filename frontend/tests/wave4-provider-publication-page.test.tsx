import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fixtures = vi.hoisted(() => {
  const agentVersionId = "version-publication-1";
  const pendingHash = "b".repeat(64);
  const confirmedHash = "c".repeat(64);
  return {
    agentVersionId,
    pendingHash,
    confirmedHash,
    list: vi.fn().mockResolvedValue({
      agent_version_id: agentVersionId,
      items: [
        {
          manifest_hash: pendingHash,
          confirmation_revision: 1,
          confirmed: false,
        },
        {
          manifest_hash: confirmedHash,
          confirmation_revision: 1,
          confirmed: true,
        },
      ],
    }),
  };
});

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: {
      listProviderDataCallPublicationManifests: fixtures.list,
    },
  }),
}));

import { TeacherProviderDataCallPublicationPage } from "../components/provider";

afterEach(() => {
  cleanup();
  fixtures.list.mockClear();
});

describe("teacher publication approval route controller", () => {
  it("discovers exact manifests by AgentVersion only in the teacher surface", async () => {
    render(
      <TeacherProviderDataCallPublicationPage
        agentVersionId={fixtures.agentVersionId}
      />,
    );

    await screen.findByText("External publication approvals");
    expect(fixtures.list).toHaveBeenCalledWith(fixtures.agentVersionId);
    expect(screen.getByText("Needs confirmation")).toBeTruthy();
    expect(screen.getByText("Confirmed")).toBeTruthy();
    const links = screen.getAllByRole("link", {
      name: "Review exact disclosure",
    });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      `/teacher/provider-disclosures/${fixtures.pendingHash}`,
      `/teacher/provider-disclosures/${fixtures.confirmedHash}`,
    ]);
    expect(document.body.textContent).not.toMatch(
      /dashscope|text-embedding|endpoint|policy hash|workspace/i,
    );
  });
});
