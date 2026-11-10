import { readFileSync } from "node:fs";
import { resolve } from "node:path";

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

// loading-v3 agent-2 (2026-11-04): the ghost agent bobs above a pixel bar.
// It replaced proposal 39 C's flipping cards.
describe("LoadingCard", () => {
  it("renders role=status with Loading…", () => {
    render(<LoadingCard />);
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("Loading…");
    expect(status.className).toContain("loading-card");
    expect(status.dataset.size).toBe("lg");
  });

  it("draws the agent over a pixel bar whose segments light in turn", () => {
    const { container } = render(<LoadingCard />);
    expect(container.querySelector(".ag.a2.lg .agent")).toBeTruthy();
    const segments = [...container.querySelectorAll<HTMLElement>(".ag .bar i")];
    expect(segments).toHaveLength(10);
    expect(parseFloat(segments[0].style.animationDelay)).toBe(0);
    expect(parseFloat(segments[9].style.animationDelay)).toBe(1.98);
    // Decoration only: the status reads as its label.
    expect(container.querySelector('.track[aria-hidden="true"]')).toBeTruthy();
    expect(container.querySelector('.bar[aria-hidden="true"]')).toBeTruthy();
  });

  it("has a small size with six segments and the label", () => {
    const { container } = render(<LoadingCard size="sm" />);
    expect(container.querySelector(".loading-card--sm .ag.sm")).toBeTruthy();
    expect(container.querySelectorAll(".ag .bar i")).toHaveLength(6);
    expect(container.querySelector(".ag .lbl")?.textContent).toBe("Loading…");
  });

  it("keeps the label for screen readers only at extra-small", () => {
    const { container } = render(<LoadingCard size="xs" />);
    expect(container.querySelector(".ag .lbl")).toBeNull();
    expect(container.querySelector(".sr-only")?.textContent).toBe("Loading…");
    expect(screen.getByRole("status").textContent).toContain("Loading…");
  });

  it("fills the whole screen as LoadingPage, on the cyan stripes", () => {
    const { container } = render(<LoadingPage />);
    const main = container.querySelector("main");
    expect(main?.className).toContain("min-h-screen");
    expect(main?.className).toContain("bg-[#67E8F9]");
    expect(main?.querySelector(".loading-card")).toBeTruthy();
  });

  it("can draw three staggered ghosts for Voices", () => {
    const { container } = render(<LoadingCard size="lg" count={3} />);
    const agents = container.querySelectorAll(".ag.a2.lg.multi .agent");
    expect(agents).toHaveLength(3);
    expect(screen.getByRole("status").dataset.count).toBe("3");
    expect(
      parseFloat((agents[0] as HTMLElement).style.animationDelay || "0"),
    ).toBe(0);
    expect(parseFloat((agents[1] as HTMLElement).style.animationDelay)).toBe(
      0.22,
    );
    expect(parseFloat((agents[2] as HTMLElement).style.animationDelay)).toBe(
      0.44,
    );
    expect(container.querySelectorAll(".ag .bar i")).toHaveLength(10);
  });

  it("accepts an explicit label override", () => {
    render(<LoadingCard label="Please wait" />);
    expect(screen.getByRole("status").textContent).toContain("Please wait");
  });

  it("keeps a definite floor so a flex or grid track cannot crush the bar", () => {
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");
    const card = css.match(/\.loading-card \{[^}]*\}/)?.[0] ?? "";
    const track = css.match(/\.ag \.track \{[^}]*\}/)?.[0] ?? "";
    const bar = css.match(/\.ag \.bar \{[^}]*\}/)?.[0] ?? "";
    expect(card).toContain("min-width: min(100%, 10rem)");
    expect(card).toContain("justify-self: stretch");
    expect(track).toContain("min-width: min(100%, var(--w))");
    expect(bar).toContain("min-width: min(100%, var(--w))");
    expect(css).toContain("min-height: min(60vh, 520px)");
  });
});
