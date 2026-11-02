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

// The arcade loading card (2026-11-02) replaced the B-v2 grey skeleton rows.
describe("LoadingCard", () => {
  it("renders role=status with Loading… on an inked card", () => {
    render(<LoadingCard />);
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("Loading…");
    expect(status.className).toContain("loading-card");
    expect(status.className).toContain("border-[3px]");
  });

  it("puts the four scholars on stage, hopping in turn, still under reduced motion", () => {
    const { container } = render(<LoadingCard />);
    const cast = [...container.querySelectorAll("svg[data-mascot]")];
    expect(cast.map((figure) => figure.getAttribute("data-mascot"))).toEqual([
      "scroll",
      "wreath",
      "tablet",
      "wave",
    ]);
    const hoppers = cast.map((figure) => figure.parentElement as HTMLElement);
    for (const hopper of hoppers) {
      expect(hopper.className).toContain("animate-loading-hop");
      expect(hopper.className).toContain("motion-reduce:animate-none");
    }
    expect(hoppers.map((hopper) => hopper.style.animationDelay)).toEqual([
      "0ms",
      "140ms",
      "280ms",
      "420ms",
    ]);
    const stripe = container.querySelector(
      '[class*="animate-loading-stripes"]',
    );
    expect(stripe?.className).toContain("motion-reduce:animate-none");
    // Decoration only: the status reads as its label.
    expect(
      container.querySelector('[aria-hidden="true"] svg[data-mascot]'),
    ).toBeTruthy();
    expect(container.querySelectorAll('[class*="bg-[#D9D9D9]"]')).toHaveLength(
      0,
    );
  });

  it("accepts an explicit label override", () => {
    render(<LoadingCard label="Please wait" />);
    expect(screen.getByRole("status").textContent).toContain("Please wait");
  });
});
