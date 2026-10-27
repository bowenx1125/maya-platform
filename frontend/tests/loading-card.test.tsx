import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/i18n", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/i18n")>();
  return {
    ...actual,
    useT: () => (k: string) => (k === "loading" ? "Loading…" : k),
  };
});

import { LoadingCard } from "../components/ui";

afterEach(cleanup);

describe("LoadingCard B-v2 skeleton", () => {
  it("renders role=status with Loading… and skeleton rows", () => {
    const { container } = render(<LoadingCard />);
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("Loading…");
    expect(status.className).toContain("border-[3px]");
    expect(status.className).toContain("shadow-[4px_5px_0_#111]");
    expect(container.querySelectorAll('[class*="bg-[#D9D9D9]"]').length).toBe(
      6,
    );
  });

  it("accepts an explicit label override", () => {
    render(<LoadingCard label="Please wait" />);
    expect(screen.getByRole("status").textContent).toContain("Please wait");
  });
});
