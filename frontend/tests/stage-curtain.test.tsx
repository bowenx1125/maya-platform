import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StageCurtain } from "../components/loading/agent-loader";

afterEach(cleanup);

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
    vi.useRealTimers();
  });
});
