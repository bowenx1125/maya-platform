import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/session-provider", () => ({
  useSession: vi.fn(),
}));

import { useSession } from "../components/session-provider";
import { AcademyIntro } from "../components/academy/intro";

const mockedUseSession = vi.mocked(useSession);

function mount(status: "loading" | "anonymous" | "authenticated") {
  mockedUseSession.mockReturnValue({ status } as never);
  return render(<AcademyIntro />);
}

function present() {
  return document.querySelector(".academy-intro");
}

describe("academy entrance", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("holds while the session is still resolving", async () => {
    mount("loading");
    expect(present()).toBeTruthy();

    // Well past the animation's own length: this is a loading screen, so a
    // slow connection keeps watching the blocks rather than a half-drawn form.
    await act(async () => {
      vi.advanceTimersByTime(8000);
    });
    expect(present()).toBeTruthy();
  });

  it("leaves once the session resolves and the sequence has played", async () => {
    const { rerender } = mount("loading");
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    expect(present()).toBeTruthy();

    mockedUseSession.mockReturnValue({ status: "anonymous" } as never);
    rerender(<AcademyIntro />);
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(present()).toBeNull();
  });

  it("plays in full even when the session is ready immediately", async () => {
    mount("anonymous");
    // A fast load should still see the mark and the blocks, not a flash.
    await act(async () => {
      vi.advanceTimersByTime(900);
    });
    expect(present()).toBeTruthy();

    // Two steps: the fade is scheduled by the effect that runs once the
    // sequence timer has fired, so it is not yet pending during that advance.
    await act(async () => {
      vi.advanceTimersByTime(1200);
    });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    expect(present()).toBeNull();
  });

  it("shows four blocks in the scholars' colours", () => {
    mount("loading");
    expect(document.querySelectorAll(".academy-intro-blocks i")).toHaveLength(
      4,
    );
    expect(document.querySelector(".academy-intro-mark")).toBeTruthy();
  });

  it("is skipped entirely when motion is not wanted", () => {
    vi.stubGlobal(
      "matchMedia",
      (query: string) =>
        ({
          matches: query.includes("prefers-reduced-motion"),
          media: query,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
          addListener: () => undefined,
          removeListener: () => undefined,
          onchange: null,
          dispatchEvent: () => false,
        }) as unknown as MediaQueryList,
    );
    mount("loading");
    expect(present()).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
  });
});
