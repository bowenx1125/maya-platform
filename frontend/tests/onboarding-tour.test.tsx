import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingTour, place } from "../components/onboarding-tour";
import { markTourPending } from "../lib/onboarding";

const show = () =>
  render(
    <>
      <OnboardingTour userId="me" />
    </>,
  );

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("first-visit tour", () => {
  it("is shown once to the account that just registered, and Skip ends it", () => {
    markTourPending("me");
    show();
    act(() => vi.advanceTimersByTime(700));
    expect(
      screen.getByRole("dialog", { name: "Welcome to Mayaform" }),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(window.localStorage.getItem("maya.tour.pending")).toBeNull();
  });

  it("is not shown to anyone else", () => {
    markTourPending("someone-else");
    show();
    act(() => vi.advanceTimersByTime(700));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("replays with ?tour, and Escape closes it", () => {
    window.history.replaceState(null, "", "/student?tour");
    show();
    act(() => vi.advanceTimersByTime(700));
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("tour card placement", () => {
  const viewport = { width: 1000, height: 600 };
  const card = { width: 360, height: 200 };

  it("sits beside the sidebar and points at the item's middle", () => {
    const spot = place(
      { top: 90, left: 8, width: 200, height: 40 },
      card,
      viewport,
    );
    expect(spot.side).toBe("right");
    expect(spot.left).toBe(8 + 200 + 22);
    expect(spot.top + spot.arrow).toBe(110);
  });

  it("goes below a wide panel when there is room, else to its left", () => {
    expect(
      place({ top: 100, left: 260, width: 600, height: 200 }, card, viewport)
        .side,
    ).toBe("below");
    expect(
      place({ top: 150, left: 620, width: 360, height: 360 }, card, viewport)
        .side,
    ).toBe("left");
  });

  it("centres the welcome card when there is nothing to point at", () => {
    expect(place(null, card, viewport)).toEqual({
      left: 320,
      top: 200,
      side: null,
      arrow: 0,
    });
  });
});
