import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ProviderDataCallDisclosure,
  type ProviderDataCallDisclosureResponse,
} from "../components/provider";

afterEach(() => cleanup());

const initial: ProviderDataCallDisclosureResponse = {
  disclosure: {
    supplier_display_name: "Alibaba Cloud Model Studio",
    region: "cn-beijing",
    purpose: "Generate the teacher-approved classroom debate speech.",
    outbound_field_classes: [
      "topic_and_platform_rules",
      "confirmed_structured_persona",
      "public_predecessor_speech",
    ],
    storage_fact:
      "The supplier stores call data as required by applicable law.",
    no_training_basis:
      "Pay-as-you-go API terms; no training use is asserted beyond them.",
    retention_setting: "unknown",
  },
  policy_hash: "a".repeat(64),
  manifest_hash: "b".repeat(64),
  confirmation_revision: 3,
};

describe("Wave 4 ProviderDataCallV1 teacher disclosure", () => {
  it("renders only disclosure facts and confirms the exact CAS material", async () => {
    const confirm = vi.fn().mockResolvedValue(initial);
    const controller = {
      load: vi.fn().mockResolvedValue(initial),
      confirm,
    };

    render(<ProviderDataCallDisclosure controller={controller} />);
    await screen.findByText("Alibaba Cloud Model Studio");
    expect(screen.getByText("cn-beijing")).toBeTruthy();
    expect(screen.getByText("unknown")).toBeTruthy();
    expect(screen.getByText("topic_and_platform_rules")).toBeTruthy();
    expect(
      screen.queryByText(/qwen|https?:\/\/|workspace|api[_-]?key/i),
    ).toBeNull();
    expect(screen.getByText(initial.policy_hash)).toBeTruthy();
    expect(screen.getByText(initial.manifest_hash)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Confirm disclosure" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(confirm).toHaveBeenCalledWith({
      policy_hash: initial.policy_hash,
      manifest_hash: initial.manifest_hash,
      expected_revision: 3,
    });
    await screen.findByRole("button", { name: "Disclosure confirmed" });
  });

  it("keeps a failed load recoverable without inventing provider facts", async () => {
    const load = vi
      .fn()
      .mockRejectedValueOnce(new Error("unavailable"))
      .mockResolvedValueOnce(initial);
    const controller = {
      load,
      confirm: vi.fn(),
    };
    render(<ProviderDataCallDisclosure controller={controller} />);
    await screen.findByRole("alert");
    expect(screen.getByText("Try again")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("Alibaba Cloud Model Studio");
    expect(load).toHaveBeenCalledTimes(2);
  });
});
