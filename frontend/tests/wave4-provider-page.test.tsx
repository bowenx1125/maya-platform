import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fixtures = vi.hoisted(() => {
  const response = {
    disclosure: {
      supplier_display_name: "Alibaba Cloud Model Studio",
      region: "cn-beijing" as const,
      purpose: "Build an approved evidence index.",
      outbound_field_classes: ["current_evidence_excerpt"],
      storage_fact: "Supplier storage is disclosed.",
      no_training_basis: "Verified account terms.",
      retention_setting: "unknown",
    },
    policy_hash: "a".repeat(64),
    manifest_hash: "b".repeat(64),
    confirmation_revision: 1,
  };
  return {
    response,
    get: vi.fn().mockResolvedValue(response),
    confirm: vi.fn().mockResolvedValue(response),
  };
});

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: {
      getProviderDataCallDisclosure: fixtures.get,
      confirmProviderDataCallDisclosure: fixtures.confirm,
    },
  }),
}));

import { TeacherProviderDataCallPage } from "../components/provider";

afterEach(() => {
  cleanup();
  fixtures.get.mockClear();
  fixtures.confirm.mockClear();
});

describe("teacher provider disclosure route controller", () => {
  it("loads and confirms only the manifest named by the route", async () => {
    render(
      <TeacherProviderDataCallPage
        manifestHash={fixtures.response.manifest_hash}
      />,
    );

    await screen.findByText("Alibaba Cloud Model Studio");
    expect(fixtures.get).toHaveBeenCalledWith(fixtures.response.manifest_hash);

    fireEvent.click(screen.getByRole("button", { name: "Confirm disclosure" }));
    await waitFor(() => expect(fixtures.confirm).toHaveBeenCalledTimes(1));
    expect(fixtures.confirm).toHaveBeenCalledWith({
      policy_hash: fixtures.response.policy_hash,
      manifest_hash: fixtures.response.manifest_hash,
      expected_revision: 1,
    });
  });
});
