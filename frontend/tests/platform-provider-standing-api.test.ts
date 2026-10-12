import { afterEach, describe, expect, it, vi } from "vitest";

import { PlatformApi } from "../lib/api/platform";

afterEach(() => vi.restoreAllMocks());

describe("PlatformApi Provider standing disclosure", () => {
  it("loads course standing disclosure with the requested course scope", async () => {
    const disclosure = {
      disclosure: {
        supplier_display_name: "Supplier",
        region: "cn-beijing",
        purpose: "Generate a Chat reply.",
        outbound_field_classes: ["private_conversation_messages"],
        storage_fact: "Storage is disclosed.",
        no_training_basis: "Account terms.",
        retention_setting: "Configured retention.",
      },
      policy_hash: "a".repeat(64),
      manifest_hash: "b".repeat(64),
      confirmation_revision: 2,
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify(disclosure), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(disclosure), { status: 200 }),
      );
    const api = new PlatformApi({ baseUrl: "/api/v1", csrfToken: "csrf" });

    expect(await api.getChatStandingProviderDisclosure("course / one")).toEqual(
      disclosure,
    );
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/provider/data-call/chat-standing/disclosure?course_id=course%20%2F%20one",
    );
    await api.getChatStandingProviderDisclosure("course-1", "embedding_query");
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/v1/provider/data-call/chat-standing/disclosure?course_id=course-1&provider_operation=embedding_query",
    );
  });

  it("previews and confirms only the exact Team resource CAS values", async () => {
    const preview = {
      team_version_id: "team-version-1",
      policy_hash: "a".repeat(64),
      resource_hash: "b".repeat(64),
      team_epoch: 4,
      publication_epoch: 7,
      member_count: 2,
      knowledge_set_count: 1,
      source_count: 3,
    };
    const confirmation = {
      ...preview,
      standing_grant_id: "grant-1",
      confirmed_at: "2026-10-05T00:00:00Z",
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify(preview), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(confirmation), { status: 200 }),
      );
    const api = new PlatformApi({ baseUrl: "/api/v1", csrfToken: "csrf" });
    const request = {
      team_version_id: preview.team_version_id,
      provider_operation: "llm_agent_chat" as const,
      policy_hash: preview.policy_hash,
    };

    expect(await api.previewTeamProviderStandingGrant(request)).toEqual(
      preview,
    );
    const confirmRequest = {
      ...request,
      expected_resource_hash: preview.resource_hash,
      expected_team_epoch: preview.team_epoch,
      expected_publication_epoch: preview.publication_epoch,
    };
    expect(await api.confirmTeamProviderStandingGrant(confirmRequest)).toEqual(
      confirmation,
    );
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/provider/data-call/team-standing-grants/preview",
      "/api/v1/provider/data-call/team-standing-grants/confirm",
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual(
      request,
    );
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual(
      confirmRequest,
    );
    expect(fetchMock.mock.calls[1][1]?.headers).toMatchObject({
      "X-CSRF-Token": "csrf",
    });
    expect(confirmation).not.toHaveProperty("provider_operation");
  });
});
