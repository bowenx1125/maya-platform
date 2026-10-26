import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Notice } from "../components/ui";
import { ErrorNotice } from "../components/ui";
import { NoticeTraySlot } from "../components/ui/error-kit";
import { TRAY_FLOW_QUERY } from "../components/notice-tray";

function setViewport({
  width,
  reduced = false,
}: {
  width: number;
  reduced?: boolean;
}) {
  window.matchMedia = vi.fn((query: string) => ({
    matches:
      query === TRAY_FLOW_QUERY
        ? width < 900
        : query === "(prefers-reduced-motion: reduce)"
          ? reduced
          : false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

function offScreen() {
  // The tray is below the fold, so a new error has to scroll to it.
  return vi
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockReturnValue({
      top: 2000,
      bottom: 2100,
      height: 100,
      left: 0,
      right: 0,
      width: 0,
      x: 0,
      y: 2000,
      toJSON: () => ({}),
    } as DOMRect);
}

const flush = () =>
  act(() => new Promise((r) => requestAnimationFrame(() => r(null))));

describe("U3 tray: in flow below 900px, fixed from 900px", () => {
  let scroll: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    scroll = vi.fn();
    HTMLElement.prototype.scrollIntoView = scroll as never;
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    document.querySelector(".notice-tray")?.remove();
  });

  it("puts the tray in the shell slot after the main panel below 900px", () => {
    setViewport({ width: 390 });
    render(
      <>
        <main>panel</main>
        <NoticeTraySlot />
        <Notice tone="error">Something broke</Notice>
      </>,
    );
    const tray = document.querySelector(".notice-tray")!;
    expect(tray.parentElement?.hasAttribute("data-notice-tray-slot")).toBe(
      true,
    );
    expect(tray.parentElement?.previousElementSibling?.tagName).toBe("MAIN");
    expect(screen.getByRole("alert").textContent).toContain("Something broke");
  });

  it("keeps the tray in <body> (fixed bottom-right, 380px) from 900px", () => {
    setViewport({ width: 1440 });
    render(
      <>
        <NoticeTraySlot />
        <Notice tone="error">Something broke</Notice>
      </>,
    );
    const tray = document.querySelector(".notice-tray")!;
    expect(tray.parentElement).toBe(document.body);
    expect(tray.className).toContain("min-[900px]:fixed");
    expect(tray.className).toContain("min-[900px]:w-[380px]");
    // body fallback padding is mobile-only, so the fixed tray is not inset at >=900px
    expect(tray.className).toContain("max-[899px]:[body>&]:px-3");
    expect(tray.className).not.toMatch(/(^| )\[body>&\]:px-3/);
  });

  it("scrolls a new off-screen error into view smoothly, once", async () => {
    setViewport({ width: 390 });
    offScreen();
    const error = new Error("boom");
    const { rerender } = render(
      <>
        <NoticeTraySlot />
        <ErrorNotice error={error} />
      </>,
    );
    await flush();
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(scroll).toHaveBeenCalledWith({
      block: "nearest",
      behavior: "smooth",
    });
    rerender(
      <>
        <NoticeTraySlot />
        <ErrorNotice error={error} />
      </>,
    );
    await flush();
    expect(scroll).toHaveBeenCalledTimes(1);
    rerender(
      <>
        <NoticeTraySlot />
        <ErrorNotice error={new Error("again")} />
      </>,
    );
    await flush();
    expect(scroll).toHaveBeenCalledTimes(2);
  });

  it("jumps without animation under prefers-reduced-motion", async () => {
    setViewport({ width: 390, reduced: true });
    offScreen();
    render(
      <>
        <NoticeTraySlot />
        <ErrorNotice error={new Error("boom")} />
      </>,
    );
    await flush();
    expect(scroll).toHaveBeenCalledWith({ block: "nearest", behavior: "auto" });
  });

  it("does not scroll from 900px, where the tray is fixed on screen", async () => {
    setViewport({ width: 1440 });
    offScreen();
    render(<ErrorNotice error={new Error("boom")} />);
    await flush();
    expect(scroll).not.toHaveBeenCalled();
  });
});
