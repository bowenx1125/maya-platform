/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DestroyConfirmPrompt } from "../components/ui/destroy-confirm";

describe("DestroyConfirmPrompt", () => {
  beforeEach(() => {
    document.querySelector(".notice-tray")?.remove();
  });
  afterEach(() => {
    cleanup();
    document.querySelector(".notice-tray")?.remove();
  });

  it("speaks from the mascot tray with opaque pink U3 chrome and red Delete", () => {
    const onCancel = vi.fn();
    const onConfirm = vi.fn();
    render(
      <DestroyConfirmPrompt
        message={"Delete notes.md?\n\nThis will affect these Agents: Ada."}
        onCancel={onCancel}
        onConfirm={onConfirm}
      />,
    );

    const dialog = screen.getByRole("alertdialog");
    expect(dialog.className).toContain("notice");
    expect(dialog.className).toMatch(/bg-\[#FFE4E4\]|ffe4e4/i);
    expect(dialog.textContent).toContain("Delete notes.md?");
    expect(dialog.textContent).toContain("This will affect these Agents: Ada.");
    expect(document.querySelector(".notice-tray")?.contains(dialog)).toBe(true);

    const deleteButton = screen.getByRole("button", { name: "Delete" });
    expect(deleteButton.className).toMatch(/bg-\[#ef4444\]|ef4444/i);
    fireEvent.click(deleteButton);
    expect(onConfirm).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("Escape cancels the confirm", () => {
    const onCancel = vi.fn();
    render(
      <DestroyConfirmPrompt
        message="Delete this custom voice?"
        onCancel={onCancel}
        onConfirm={vi.fn()}
      />,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
