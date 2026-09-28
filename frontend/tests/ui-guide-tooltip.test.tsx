import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { UiGuideTooltip } from "../components/ui-guide-tooltip";
import { LocaleProvider, useLocale } from "../components/locale";

const originalInnerWidth = Object.getOwnPropertyDescriptor(
  window,
  "innerWidth",
);
const originalInnerHeight = Object.getOwnPropertyDescriptor(
  window,
  "innerHeight",
);

afterEach(() => {
  cleanup();
  if (originalInnerWidth)
    Object.defineProperty(window, "innerWidth", originalInnerWidth);
  if (originalInnerHeight)
    Object.defineProperty(window, "innerHeight", originalInnerHeight);
});

function LocaleSwitch() {
  const { setLocale } = useLocale();
  return (
    <button type="button" onClick={() => setLocale("zh")}>
      Switch locale
    </button>
  );
}

function renderGuide(locale: "en" | "zh" = "en") {
  return render(
    <LocaleProvider initialLocale={locale}>
      <UiGuideTooltip />
      <button
        type="button"
        data-ui-guide="knowledge.edit"
        data-ui-guide-touch="true"
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

  it("keeps the focused control described when the locale changes", () => {
    render(
      <LocaleProvider initialLocale="en">
        <UiGuideTooltip />
        <button
          type="button"
          data-ui-guide="knowledge.edit"
          aria-describedby="existing-description"
        >
          Edit
        </button>
        <LocaleSwitch />
      </LocaleProvider>,
    );
    const button = screen.getByRole("button", { name: "Edit" });

    fireEvent.focusIn(button);
    fireEvent.click(screen.getByRole("button", { name: "Switch locale" }));

    expect(screen.getByRole("tooltip").textContent).toContain(
      "Markdown 编辑器",
    );
    expect(button.getAttribute("aria-describedby")).toBe(
      "existing-description maya-ui-guide-tooltip",
    );
  });

  it("pins touch help until the same guided control is tapped again", () => {
    renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });

    fireEvent.pointerUp(button, { pointerType: "touch" });

    expect(screen.getByRole("tooltip").textContent).toContain(
      "Markdown editor",
    );

    fireEvent.pointerUp(button, { pointerType: "touch" });

    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("repositions focused help after scrolling and resizing", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1000,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 800,
    });
    let targetTop = 100;
    const buttonRect = () =>
      ({
        left: 100,
        right: 180,
        top: targetTop,
        bottom: targetTop + 30,
        width: 80,
        height: 30,
        x: 100,
        y: targetTop,
        toJSON: () => ({}),
      }) as DOMRect;
    renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });
    const tooltip = {
      width: 100,
      height: 30,
      left: 0,
      right: 100,
      top: 0,
      bottom: 30,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect;
    button.getBoundingClientRect = buttonRect;

    fireEvent.focusIn(button);
    const tooltipElement = screen.getByRole("tooltip");
    tooltipElement.getBoundingClientRect = () => tooltip;
    expect(tooltipElement.style.top).toBe("140px");

    targetTop = 50;
    fireEvent.scroll(document);
    expect(tooltipElement.style.top).toBe("90px");

    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 150,
    });
    fireEvent.resize(window);
    expect(tooltipElement.style.left).toBe("42px");
  });
});
