import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { celebrate } from "../lib/confetti";

function layer(): HTMLElement | null {
  return document.querySelector("[data-confetti]");
}

describe("celebrate", () => {
  const original = HTMLElement.prototype.animate;

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    HTMLElement.prototype.animate = original;
    layer()?.remove();
  });

  function motion(reduce: boolean) {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: reduce && query.includes("reduce"),
      })),
    );
  }

  it("fires two cannons across the page that never take clicks, then cleans up", () => {
    motion(false);
    const animate = vi.fn();
    HTMLElement.prototype.animate =
      animate as unknown as typeof HTMLElement.prototype.animate;
    celebrate();
    const node = layer();
    expect(node).not.toBeNull();
    expect(node?.getAttribute("aria-hidden")).toBe("true");
    expect(node?.style.pointerEvents).toBe("none");
    expect(node?.style.position).toBe("fixed");
    expect(node?.children.length).toBe(140);
    expect(animate).toHaveBeenCalledTimes(140);
    vi.advanceTimersByTime(3100);
    expect(layer()).toBeNull();
  });

  it("stays still for reduced motion", () => {
    motion(true);
    HTMLElement.prototype.animate =
      vi.fn() as unknown as typeof HTMLElement.prototype.animate;
    celebrate();
    expect(layer()).toBeNull();
  });

  it("does nothing where the Web Animations API is missing", () => {
    motion(false);
    // jsdom has no Element.animate.
    HTMLElement.prototype.animate =
      undefined as unknown as typeof HTMLElement.prototype.animate;
    celebrate();
    expect(layer()).toBeNull();
  });
});
