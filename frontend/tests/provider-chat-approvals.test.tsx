import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fixtures = vi.hoisted(() => {
  const disclosure = {
    disclosure: {
      supplier_display_name: "Supplier",
      region: "cn-beijing" as const,
      purpose:
        "Generate a Chat reply from authorized conversation and course material.",
      outbound_field_classes: ["private_conversation_messages"],
      storage_fact: "Storage is disclosed.",
      no_training_basis: "Account terms.",
      retention_setting: "Configured retention.",
    },
    policy_hash: "a".repeat(64),
    manifest_hash: "b".repeat(64),
    confirmation_revision: 2,
  };
  const embeddingDisclosure = {
    ...disclosure,
    disclosure: {
      ...disclosure.disclosure,
      purpose:
        "Embed approved retrieval questions to search one immutable evidence snapshot.",
      outbound_field_classes: ["current_evidence_excerpt"],
    },
    policy_hash: "d".repeat(64),
    manifest_hash: "e".repeat(64),
  };
  const preview = {
    team_version_id: "team-version-1",
    policy_hash: disclosure.policy_hash,
    resource_hash: "c".repeat(64),
    team_epoch: 4,
    publication_epoch: 7,
    member_count: 2,
    knowledge_set_count: 1,
    source_count: 3,
  };
  const embeddingPreview = {
    ...preview,
    policy_hash: embeddingDisclosure.policy_hash,
    resource_hash: "f".repeat(64),
  };
  const api = {
    getChatStandingProviderDisclosure: vi
      .fn()
      .mockImplementation((_courseId: string, providerOperation?: string) =>
        Promise.resolve(
          providerOperation === "embedding_query"
            ? embeddingDisclosure
            : disclosure,
        ),
      ),
    confirmProviderDataCallDisclosure: vi
      .fn()
      .mockImplementation((request: { policy_hash: string }) =>
        Promise.resolve(
          request.policy_hash === embeddingDisclosure.policy_hash
            ? embeddingDisclosure
            : disclosure,
        ),
      ),
    teams: vi.fn().mockResolvedValue([
      {
        id: "team-1",
        owner_user_id: "teacher-1",
        display_name: "Published Team",
        ownership_scope: "personal",
        visibility: "public",
        can_edit: true,
      },
      {
        id: "team-private",
        owner_user_id: "teacher-1",
        display_name: "Private Team",
        ownership_scope: "personal",
        visibility: "private",
        can_edit: true,
      },
    ]),
    team: vi.fn().mockResolvedValue({
      id: "team-1",
      course_id: "course-1",
      owner_user_id: "teacher-1",
      ownership_scope: "personal",
      group_id: null,
      display_name: "Published Team",
      visibility: "public",
      metadata_revision: 1,
      authorization_epoch: 4,
      current_version_id: "team-version-1",
      current_version_seq: 2,
      member_count: 2,
      can_edit: true,
      created_at: "2026-10-01T00:00:00Z",
      updated_at: "2026-10-01T00:00:00Z",
      members: [],
      shared_knowledge_set_ids: [],
      publication_state: "published",
    }),
    previewTeamProviderStandingGrant: vi
      .fn()
      .mockImplementation((request: { provider_operation: string }) =>
        Promise.resolve(
          request.provider_operation === "embedding_query"
            ? embeddingPreview
            : preview,
        ),
      ),
    confirmTeamProviderStandingGrant: vi
      .fn()
      .mockImplementation((request: { provider_operation: string }) => {
        const confirmedPreview =
          request.provider_operation === "embedding_query"
            ? embeddingPreview
            : preview;
        return Promise.resolve({
          ...confirmedPreview,
          standing_grant_id: "grant-1",
          confirmed_at: "2026-10-05T00:00:00Z",
        });
      }),
  };
  return {
    disclosure,
    embeddingDisclosure,
    preview,
    embeddingPreview,
    api,
  };
});

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: fixtures.api,
    identityGeneration: 1,
    user: { id: "teacher-1" },
  }),
}));

import { TeacherChatProviderApprovalsPage } from "../components/provider/provider-chat-approvals";

afterEach(() => {
  cleanup();
  fixtures.api.getChatStandingProviderDisclosure.mockClear();
  fixtures.api.getChatStandingProviderDisclosure.mockImplementation(
    (_courseId: string, providerOperation?: string) =>
      Promise.resolve(
        providerOperation === "embedding_query"
          ? fixtures.embeddingDisclosure
          : fixtures.disclosure,
      ),
  );
  fixtures.api.confirmProviderDataCallDisclosure.mockClear();
  fixtures.api.teams.mockClear();
  fixtures.api.team.mockClear();
  fixtures.api.previewTeamProviderStandingGrant.mockClear();
  fixtures.api.confirmTeamProviderStandingGrant.mockClear();
});

describe("teacher Chat Provider approval page", () => {
  it("confirms only the visible course disclosure and exact published Team binding", async () => {
    let courseDisclosureReads = 0;
    const laterDisclosure = {
      ...fixtures.disclosure,
      policy_hash: "9".repeat(64),
      manifest_hash: "8".repeat(64),
    };
    fixtures.api.getChatStandingProviderDisclosure.mockImplementation(
      (_courseId: string, providerOperation?: string) => {
        if (providerOperation === "embedding_query") {
          return Promise.resolve(fixtures.embeddingDisclosure);
        }
        courseDisclosureReads += 1;
        return Promise.resolve(
          courseDisclosureReads === 1 ? fixtures.disclosure : laterDisclosure,
        );
      },
    );
    render(<TeacherChatProviderApprovalsPage courseId="course-1" />);

    await waitFor(() =>
      expect(
        screen.getAllByRole("heading", { name: "External data disclosure" }),
      ).toHaveLength(2),
    );
    await screen.findByText("Published Team · Chat reply");
    expect(fixtures.api.getChatStandingProviderDisclosure).toHaveBeenCalledWith(
      "course-1",
    );
    expect(fixtures.api.getChatStandingProviderDisclosure).toHaveBeenCalledWith(
      "course-1",
      "embedding_query",
    );
    expect(
      fixtures.api.getChatStandingProviderDisclosure,
    ).toHaveBeenCalledTimes(2);
    expect(fixtures.api.teams).toHaveBeenCalledWith("course-1");
    expect(fixtures.api.team).toHaveBeenCalledWith("team-1");
    expect(fixtures.api.team).not.toHaveBeenCalledWith("team-private");
    expect(fixtures.api.previewTeamProviderStandingGrant).toHaveBeenCalledWith({
      team_version_id: "team-version-1",
      provider_operation: "llm_agent_chat",
      policy_hash: fixtures.disclosure.policy_hash,
    });
    expect(fixtures.api.previewTeamProviderStandingGrant).toHaveBeenCalledWith({
      team_version_id: "team-version-1",
      provider_operation: "embedding_query",
      policy_hash: fixtures.embeddingDisclosure.policy_hash,
    });
    expect(
      await screen.findByText(fixtures.preview.resource_hash),
    ).toBeTruthy();
    await waitFor(() =>
      expect(
        screen.getAllByText(fixtures.embeddingDisclosure.policy_hash),
      ).toHaveLength(2),
    );
    expect(screen.getByText("current_evidence_excerpt")).toBeTruthy();
    expect(screen.getAllByText(fixtures.preview.policy_hash)).toHaveLength(2);
    expect(screen.getAllByText("Team version: team-version-1")).toHaveLength(2);
    expect(document.body.textContent).not.toMatch(
      /PRIVATE_STUDENT_MESSAGE_CANARY|turn[_ ]?id|endpoint|api[_ ]?key|llm_agent_chat/i,
    );
    expect(document.body.textContent).not.toMatch(
      /source count|member count|knowledge set count/i,
    );

    const courseDisclosureButtons = screen.getAllByRole("button", {
      name: "Confirm disclosure",
    });
    expect(courseDisclosureButtons).toHaveLength(2);
    fireEvent.click(courseDisclosureButtons[0]);
    await waitFor(() =>
      expect(
        fixtures.api.confirmProviderDataCallDisclosure,
      ).toHaveBeenCalledWith({
        policy_hash: fixtures.disclosure.policy_hash,
        manifest_hash: fixtures.disclosure.manifest_hash,
        expected_revision: fixtures.disclosure.confirmation_revision,
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Confirm disclosure" }));
    await waitFor(() =>
      expect(
        fixtures.api.confirmProviderDataCallDisclosure,
      ).toHaveBeenCalledWith({
        policy_hash: fixtures.embeddingDisclosure.policy_hash,
        manifest_hash: fixtures.embeddingDisclosure.manifest_hash,
        expected_revision: fixtures.embeddingDisclosure.confirmation_revision,
      }),
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Confirm Chat reply resources" }),
    );
    await waitFor(() =>
      expect(
        fixtures.api.confirmTeamProviderStandingGrant,
      ).toHaveBeenCalledWith({
        team_version_id: "team-version-1",
        provider_operation: "llm_agent_chat",
        policy_hash: fixtures.preview.policy_hash,
        expected_resource_hash: fixtures.preview.resource_hash,
        expected_team_epoch: fixtures.preview.team_epoch,
        expected_publication_epoch: fixtures.preview.publication_epoch,
      }),
    );
    expect(
      await screen.findByText(/Confirmed for this exact Team resource binding/),
    ).toBeTruthy();
    expect(screen.getAllByText("Confirmed")).toHaveLength(2);
    expect(
      screen.getByRole("button", {
        name: "Confirm Knowledge retrieval resources",
      }),
    ).toBeTruthy();
    expect(
      fixtures.api.confirmTeamProviderStandingGrant,
    ).not.toHaveBeenCalledWith(
      expect.objectContaining({ provider_operation: "embedding_query" }),
    );
  });

  it("keeps both exact Team purposes confirmable under StrictMode", async () => {
    render(
      <StrictMode>
        <TeacherChatProviderApprovalsPage courseId="course-1" />
      </StrictMode>,
    );

    await waitFor(() => {
      expect(
        screen
          .getByRole("button", { name: "Confirm Chat reply resources" })
          .getAttribute("disabled"),
      ).toBeNull();
      expect(
        screen
          .getByRole("button", {
            name: "Confirm Knowledge retrieval resources",
          })
          .getAttribute("disabled"),
      ).toBeNull();
    });
    expect(fixtures.api.previewTeamProviderStandingGrant).toHaveBeenCalledWith({
      team_version_id: "team-version-1",
      provider_operation: "llm_agent_chat",
      policy_hash: fixtures.preview.policy_hash,
    });
    expect(fixtures.api.previewTeamProviderStandingGrant).toHaveBeenCalledWith({
      team_version_id: "team-version-1",
      provider_operation: "embedding_query",
      policy_hash: fixtures.embeddingPreview.policy_hash,
    });

    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirm Knowledge retrieval resources",
      }),
    );
    await waitFor(() =>
      expect(
        fixtures.api.confirmTeamProviderStandingGrant,
      ).toHaveBeenCalledWith({
        team_version_id: "team-version-1",
        provider_operation: "embedding_query",
        policy_hash: fixtures.embeddingPreview.policy_hash,
        expected_resource_hash: fixtures.embeddingPreview.resource_hash,
        expected_team_epoch: fixtures.embeddingPreview.team_epoch,
        expected_publication_epoch: fixtures.embeddingPreview.publication_epoch,
      }),
    );
    expect(
      fixtures.api.confirmTeamProviderStandingGrant,
    ).not.toHaveBeenCalledWith(
      expect.objectContaining({ provider_operation: "llm_agent_chat" }),
    );
  });
});
