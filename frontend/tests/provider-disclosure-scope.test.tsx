import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  api: {} as Record<string, any>,
  identityGeneration: 1,
  user: { id: "teacher-a" },
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => session,
}));

import type {
  ProviderDataCallDisclosureResponse,
  TeamStandingGrantConfirmation,
  TeamStandingGrantPreview,
} from "../lib/api";
import {
  ProviderDataCallDisclosure,
  type ProviderDataCallDisclosureController,
} from "../components/provider/provider-data-call-disclosure";
import { TeacherChatProviderApprovalsPage } from "../components/provider/provider-chat-approvals";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function disclosure(
  supplier: string,
  hash: string,
): ProviderDataCallDisclosureResponse {
  return {
    disclosure: {
      supplier_display_name: supplier,
      region: "cn-beijing",
      purpose: "Generate an authorized Chat reply.",
      outbound_field_classes: ["private_conversation_messages"],
      storage_fact: "Storage is disclosed.",
      no_training_basis: "Account terms.",
      retention_setting: "Configured retention.",
    },
    policy_hash: hash.repeat(64),
    manifest_hash: hash.repeat(64),
    confirmation_revision: 2,
  };
}

const supplierA = disclosure("Supplier A", "a");
const supplierB = disclosure("Supplier B", "b");
const teamPreview: TeamStandingGrantPreview = {
  team_version_id: "team-version-a",
  policy_hash: supplierA.policy_hash,
  resource_hash: "c".repeat(64),
  team_epoch: 4,
  publication_epoch: 7,
  member_count: 2,
  knowledge_set_count: 1,
  source_count: 3,
};

function teamSummary(ownerUserId = "teacher-a") {
  return {
    id: "team-a",
    owner_user_id: ownerUserId,
    display_name: "Teacher A Team",
    current_version_id: teamPreview.team_version_id,
    ownership_scope: "personal" as const,
    visibility: "public" as const,
    can_edit: true,
  };
}

function teamDetail(ownerUserId = "teacher-a") {
  return {
    ...teamSummary(ownerUserId),
    course_id: "course-1",
    group_id: null,
    metadata_revision: 1,
    authorization_epoch: 4,
    current_version_seq: 2,
    member_count: 2,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    members: [],
    shared_knowledge_set_ids: [],
    publication_state: "published" as const,
  };
}

afterEach(() => {
  cleanup();
  session.api = {};
  session.identityGeneration = 1;
  session.user = { id: "teacher-a" };
});

describe("Provider disclosure request scopes", () => {
  it("does not let a prior course disclosure load replace the current one", async () => {
    const pending = deferred<ProviderDataCallDisclosureResponse>();
    const oldController: ProviderDataCallDisclosureController = {
      load: vi.fn(() => pending.promise),
      confirm: vi.fn(async () => supplierA),
    };
    const currentController: ProviderDataCallDisclosureController = {
      load: vi.fn(async () => supplierB),
      confirm: vi.fn(async () => supplierB),
    };
    const view = render(
      <ProviderDataCallDisclosure
        controller={oldController}
        scopeKey="teacher-a:course-a"
      />,
    );
    await waitFor(() => expect(oldController.load).toHaveBeenCalledTimes(1));

    view.rerender(
      <ProviderDataCallDisclosure
        controller={currentController}
        scopeKey="teacher-a:course-b"
      />,
    );
    await screen.findByText("Supplier B");
    await act(async () => pending.resolve(supplierA));

    expect(screen.queryByText("Supplier A")).toBeNull();
    expect(screen.getByText("Supplier B")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm disclosure" }));
    await waitFor(() =>
      expect(currentController.confirm).toHaveBeenCalledWith({
        policy_hash: supplierB.policy_hash,
        manifest_hash: supplierB.manifest_hash,
        expected_revision: supplierB.confirmation_revision,
      }),
    );
  });

  it("keeps an external disclosure confirmation failure visible and retryable", async () => {
    const onRetry = vi.fn();
    const controller: ProviderDataCallDisclosureController = {
      load: vi.fn(async () => supplierB),
      confirm: vi.fn(async () => {
        throw new Error("confirmation failed");
      }),
    };
    render(
      <ProviderDataCallDisclosure
        controller={controller}
        scopeKey="teacher-a:course-a"
        existingDisclosure={supplierA}
        existingDisclosureError={null}
        onRetry={onRetry}
      />,
    );

    await screen.findByText("Supplier A");
    fireEvent.click(screen.getByRole("button", { name: "Confirm disclosure" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "could not be loaded",
    );
    expect(controller.load).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("does not let a late old-course confirmation confirm the current disclosure", async () => {
    const pending = deferred<ProviderDataCallDisclosureResponse>();
    const oldController: ProviderDataCallDisclosureController = {
      load: vi.fn(async () => supplierA),
      confirm: vi.fn(() => pending.promise),
    };
    const currentController: ProviderDataCallDisclosureController = {
      load: vi.fn(async () => supplierB),
      confirm: vi.fn(async () => supplierB),
    };
    const view = render(
      <ProviderDataCallDisclosure
        controller={oldController}
        scopeKey="teacher-a:course-a"
      />,
    );
    await screen.findByText("Supplier A");
    fireEvent.click(screen.getByRole("button", { name: "Confirm disclosure" }));
    await waitFor(() => expect(oldController.confirm).toHaveBeenCalledTimes(1));

    view.rerender(
      <ProviderDataCallDisclosure
        controller={currentController}
        scopeKey="teacher-a:course-b"
      />,
    );
    await screen.findByText("Supplier B");
    await act(async () => pending.resolve(supplierA));

    expect(screen.queryByText("Supplier A")).toBeNull();
    expect(screen.getByText("Supplier B")).toBeTruthy();
    expect(screen.getByText("Needs confirmation")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Confirm disclosure" }),
    ).toBeTruthy();
  });

  it("filters a late prior-Teacher Team list after an identity switch on a stable API", async () => {
    const pending = deferred<ReturnType<typeof teamSummary>[]>();
    const api = {
      getChatStandingProviderDisclosure: vi.fn(async () => supplierA),
      confirmProviderDataCallDisclosure: vi.fn(async () => supplierA),
      teams: vi.fn(() => pending.promise),
      team: vi.fn(async () => teamDetail()),
      previewTeamProviderStandingGrant: vi.fn(async () => teamPreview),
      confirmTeamProviderStandingGrant: vi.fn(),
    };
    session.api = api;
    const view = render(
      <TeacherChatProviderApprovalsPage courseId="course-1" />,
    );
    await waitFor(() => expect(api.teams).toHaveBeenCalledTimes(1));

    session.user = { id: "teacher-b" };
    session.identityGeneration = 2;
    view.rerender(<TeacherChatProviderApprovalsPage courseId="course-1" />);
    await waitFor(() => expect(api.teams).toHaveBeenCalledTimes(2));
    await act(async () => pending.resolve([teamSummary("teacher-a")]));
    await waitFor(() =>
      expect(screen.queryByText("Loading published Teams…")).toBeNull(),
    );

    expect(screen.queryByText("Teacher A Team")).toBeNull();
    expect(
      screen.queryByText(`Team version: ${teamPreview.team_version_id}`),
    ).toBeNull();
    expect(api.team).not.toHaveBeenCalled();
  });

  it("ignores a Team preview that finishes after its Teacher leaves the scope", async () => {
    const pending = deferred<TeamStandingGrantPreview>();
    const api = {
      getChatStandingProviderDisclosure: vi.fn(async () => supplierA),
      confirmProviderDataCallDisclosure: vi.fn(async () => supplierA),
      teams: vi.fn(async () => [teamSummary()]),
      team: vi.fn(async () => teamDetail()),
      previewTeamProviderStandingGrant: vi.fn(() => pending.promise),
      confirmTeamProviderStandingGrant: vi.fn(),
    };
    session.api = api;
    const view = render(
      <TeacherChatProviderApprovalsPage courseId="course-1" />,
    );
    await waitFor(() =>
      expect(api.previewTeamProviderStandingGrant).toHaveBeenCalled(),
    );

    session.user = { id: "teacher-b" };
    session.identityGeneration = 2;
    view.rerender(<TeacherChatProviderApprovalsPage courseId="course-1" />);
    await act(async () => pending.resolve(teamPreview));
    await waitFor(() =>
      expect(screen.queryByText("Loading published Teams…")).toBeNull(),
    );

    expect(screen.queryByText("Teacher A Team")).toBeNull();
    expect(screen.queryByText(teamPreview.resource_hash)).toBeNull();
    expect(api.previewTeamProviderStandingGrant).toHaveBeenCalledTimes(2);
  });

  it("ignores a Team confirmation that finishes after its Teacher leaves the scope", async () => {
    const pending = deferred<TeamStandingGrantConfirmation>();
    const api = {
      getChatStandingProviderDisclosure: vi.fn(async () => supplierA),
      confirmProviderDataCallDisclosure: vi.fn(async () => supplierA),
      teams: vi.fn(async () => [teamSummary()]),
      team: vi.fn(async () => teamDetail()),
      previewTeamProviderStandingGrant: vi.fn(async () => teamPreview),
      confirmTeamProviderStandingGrant: vi.fn(() => pending.promise),
    };
    session.api = api;
    const view = render(
      <TeacherChatProviderApprovalsPage courseId="course-1" />,
    );
    await screen.findByRole("button", { name: "Confirm Chat reply resources" });
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm Chat reply resources" }),
    );
    await waitFor(() =>
      expect(api.confirmTeamProviderStandingGrant).toHaveBeenCalledWith({
        team_version_id: teamPreview.team_version_id,
        provider_operation: "llm_agent_chat",
        policy_hash: teamPreview.policy_hash,
        expected_resource_hash: teamPreview.resource_hash,
        expected_team_epoch: teamPreview.team_epoch,
        expected_publication_epoch: teamPreview.publication_epoch,
      }),
    );

    session.user = { id: "teacher-b" };
    session.identityGeneration = 2;
    view.rerender(<TeacherChatProviderApprovalsPage courseId="course-1" />);
    await act(async () =>
      pending.resolve({
        ...teamPreview,
        standing_grant_id: "old-grant",
        confirmed_at: "2026-10-05T00:00:00Z",
      }),
    );
    await waitFor(() =>
      expect(screen.queryByText("Loading published Teams…")).toBeNull(),
    );

    expect(
      screen.queryByText(/Confirmed for this exact Team resource binding/),
    ).toBeNull();
    expect(screen.queryByText("Teacher A Team")).toBeNull();
  });
});
