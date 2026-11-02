import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/i18n", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/i18n")>();
  return {
    ...actual,
    useT: () => (k: string) => (k === "loading" ? "Loading…" : k),
  };
});

import { LoadingCard, LoadingPage } from "../components/ui";

afterEach(cleanup);

// Proposal 39 C (2026-11-02): the character cards flip in turn. It replaced
// the B-v2 grey skeleton rows and the interim hopping strip.
describe("LoadingCard", () => {
  it("renders role=status with Loading…", () => {
    render(<LoadingCard />);
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("Loading…");
    expect(status.className).toContain("loading-card");
    expect(status.className).toContain("@container");
  });

  it("flips the four scholars' cards one after another, face up under reduced motion", () => {
    const { container } = render(<LoadingCard />);
    const cast = [...container.querySelectorAll("svg[data-mascot]")];
    expect(cast.map((figure) => figure.getAttribute("data-mascot"))).toEqual([
      "scroll",
      "wreath",
      "tablet",
      "wave",
    ]);
    const cards = [
      ...container.querySelectorAll<HTMLElement>(
        '[class*="animate-loading-flip"]',
      ),
    ];
    expect(cards).toHaveLength(4);
    for (const card of cards) {
      expect(card.className).toContain("motion-reduce:animate-none");
      expect(card.className).toContain(
        "motion-reduce:[transform:rotateY(180deg)]",
      );
    }
    expect(cards.map((card) => card.style.animationDelay)).toEqual([
      "0s",
      "0.8s",
      "1.6s",
      "2.4s",
    ]);
    // Each card holds its scholar on the face that turns up.
    cards.forEach((card, index) =>
      expect(card.contains(cast[index])).toBe(true),
    );
    // Decoration only: the status reads as its label.
    expect(
      container.querySelector('[aria-hidden="true"] svg[data-mascot]'),
    ).toBeTruthy();
    expect(container.querySelectorAll('[class*="bg-[#D9D9D9]"]')).toHaveLength(
      0,
    );
  });

  it("lights four dots in step with the cards", () => {
    const { container } = render(<LoadingCard />);
    const dots = [
      ...container.querySelectorAll<HTMLElement>(
        '[class*="animate-loading-dot"]',
      ),
    ];
    expect(dots).toHaveLength(4);
    expect(dots.map((dot) => dot.style.animationDelay)).toEqual([
      "0s",
      "0.8s",
      "1.6s",
      "2.4s",
    ]);
    for (const dot of dots) {
      expect(dot.className).toContain("motion-reduce:animate-none");
    }
  });

  it("frames itself in a content area, but not when bare", () => {
    const panel = (node: HTMLElement) =>
      node.querySelector(".loading-card > div")?.className ?? "";
    const framed = render(<LoadingCard />);
    expect(panel(framed.container)).toContain("@min-[640px]:border-[4px]");
    expect(panel(framed.container)).toContain("@min-[640px]:bg-[#67E8F9]");
    framed.unmount();
    const bare = render(<LoadingCard bare />);
    expect(panel(bare.container)).not.toContain("border-[4px]");
    expect(panel(bare.container)).not.toContain("bg-[#67E8F9]");
  });

  it("fills the whole screen as LoadingPage, on the cyan stripes", () => {
    const { container } = render(<LoadingPage />);
    const main = container.querySelector("main");
    expect(main?.className).toContain("min-h-screen");
    expect(main?.className).toContain("bg-[#67E8F9]");
    expect(main?.querySelector(".loading-card")).toBeTruthy();
  });

  it("accepts an explicit label override", () => {
    render(<LoadingCard label="Please wait" />);
    expect(screen.getByRole("status").textContent).toContain("Please wait");
  });
});
