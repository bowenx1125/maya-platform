/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EndRunningDebatePrompt } from "../components/debate-beta/stage/end-running-debate-prompt";

describe("EndRunningDebatePrompt", () => {
  beforeEach(() => {
    document.querySelector(".notice-tray")?.remove();
  });
  afterEach(() => {
    cleanup();
    document.querySelector(".notice-tray")?.remove();
  });

  it("speaks from the mascot tray with opaque pink U3 chrome and soft-danger End", () => {
    const onCancel = vi.fn();
    const onEnd = vi.fn();
    render(
      <EndRunningDebatePrompt
        topic="Click-test topic"
        zh={false}
        busy={false}
        canEnd
        onCancel={onCancel}
        onEnd={onEnd}
      />,
    );

    const dialog = screen.getByRole("alertdialog");
    expect(dialog.className).toContain("notice");
    expect(dialog.className).toMatch(/bg-\[#FFE4E4\]|ffe4e4/i);
    expect(dialog.textContent).toContain(
      "“Click-test topic” is running. End that debate?",
    );
    expect(document.querySelector(".notice-tray")?.contains(dialog)).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "End" }));
    expect(onEnd).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("Escape cancels the confirm", () => {
    const onCancel = vi.fn();
    render(
      <EndRunningDebatePrompt
        topic="T"
        zh
        busy={false}
        canEnd
        onCancel={onCancel}
        onEnd={vi.fn()}
      />,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
