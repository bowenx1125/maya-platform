import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StageCurtain } from "../components/loading/agent-loader";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("StageCurtain", () => {
  it("shows the label as a status, then opens and leaves", () => {
    vi.useFakeTimers();
    const view = render(
      <StageCurtain loading label="Setting out the bench…" />,
    );
    expect(screen.getByRole("status").textContent).toBe(
      "Setting out the bench…",
    );
    view.rerender(
      <StageCurtain loading={false} label="Setting out the bench…" />,
    );
    expect(screen.getByTestId("stage-curtain").className).toContain("open");
    act(() => vi.advanceTimersByTime(600));
    expect(screen.queryByTestId("stage-curtain")).toBeNull();
  });
});

describe("StageCurtain loading failures", () => {
  it("opens after three seconds even if assets never settle", () => {
    vi.useFakeTimers();
    render(<StageCurtain loading label="Setting out the bench…" />);
    act(() => vi.advanceTimersByTime(2999));
    expect(screen.getByTestId("stage-curtain").className).not.toContain("open");
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByTestId("stage-curtain").className).toContain("open");
    act(() => vi.advanceTimersByTime(600));
    expect(screen.queryByTestId("stage-curtain")).toBeNull();
  });

  it("does not close again when loading changes after opening", () => {
    vi.useFakeTimers();
    const view = render(
      <StageCurtain loading label="Setting out the bench…" />,
    );
    view.rerender(
      <StageCurtain loading={false} label="Setting out the bench…" />,
    );
    view.rerender(<StageCurtain loading label="Setting out the bench…" />);
    expect(screen.getByTestId("stage-curtain").className).toContain("open");
    act(() => vi.advanceTimersByTime(600));
    expect(screen.queryByTestId("stage-curtain")).toBeNull();
    view.rerender(
      <StageCurtain loading={false} label="Setting out the bench…" />,
    );
    view.rerender(<StageCurtain loading label="Setting out the bench…" />);
    expect(screen.queryByTestId("stage-curtain")).toBeNull();
  });

  it("cleans up the fallback timer when unmounted", () => {
    vi.useFakeTimers();
    const view = render(
      <StageCurtain loading label="Setting out the bench…" />,
    );
    expect(vi.getTimerCount()).toBe(1);
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
