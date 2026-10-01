import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CountUp } from "../components/count-up";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function stubMotion(reduce: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query.includes("reduce") ? reduce : !reduce,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

describe("CountUp", () => {
  it("runs from zero and settles on the value", () => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "performance"] });
    stubMotion(false);
    render(<CountUp value={12} />);
    expect(screen.getByText("0")).toBeTruthy();
    act(() => vi.advanceTimersByTime(300));
    const midway = Number(document.body.textContent);
    expect(midway).toBeGreaterThan(0);
    expect(midway).toBeLessThan(12);
    act(() => vi.advanceTimersByTime(1000));
    expect(document.body.textContent).toBe("12");
  });

  it("shows the value at once without matchMedia", () => {
    render(<CountUp value={7} />);
    expect(document.body.textContent).toBe("7");
  });

  it("shows the new value when it changes to zero after running", () => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "performance"] });
    stubMotion(false);
    const view = render(<CountUp value={4} />);
    act(() => vi.advanceTimersByTime(1200));
    view.rerender(<CountUp value={0} />);
    expect(document.body.textContent).toBe("0");
  });
});
