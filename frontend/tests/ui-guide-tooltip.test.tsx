import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { UiGuideTooltip } from "../components/ui-guide-tooltip";
import { LocaleProvider } from "../components/locale";

afterEach(cleanup);

function renderGuide(locale: "en" | "zh" = "en") {
  return render(
    <LocaleProvider initialLocale={locale}>
      <UiGuideTooltip />
      <button
        type="button"
        data-ui-guide="knowledge.edit"
        aria-describedby="existing-description"
      >
        Edit
      </button>
    </LocaleProvider>,
  );
}

describe("workspace UI guide tooltip", () => {
  it("follows the pointer and restores an existing description on pointer leave", () => {
    renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });

    fireEvent.pointerOver(button, {
      pointerType: "mouse",
      clientX: 32,
      clientY: 48,
    });

    expect(screen.getByRole("tooltip").textContent).toContain(
      "Markdown editor",
    );
    expect(button.getAttribute("aria-describedby")).toBe(
      "existing-description maya-ui-guide-tooltip",
    );

    fireEvent.pointerOut(button, { relatedTarget: document.body });

    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(button.getAttribute("aria-describedby")).toBe(
      "existing-description",
    );
  });

  it("shows localized help on keyboard focus", () => {
    renderGuide("zh");
    const button = screen.getByRole("button", { name: "Edit" });

    fireEvent.focusIn(button);

    expect(screen.getByRole("tooltip").textContent).toContain(
      "Markdown 编辑器",
    );

    fireEvent.focusOut(button, { relatedTarget: document.body });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});
