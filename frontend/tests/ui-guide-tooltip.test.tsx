import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UiGuideTooltip } from "../components/ui-guide-tooltip";
import { LocaleProvider } from "../components/locale";

const route = vi.hoisted(() => ({ pathname: "/student/workspace" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.pathname }));

beforeEach(() => {
  route.pathname = "/student/workspace";
});
afterEach(cleanup);

function guideContent(locale: "en" | "zh" = "en", showButton = true) {
  return (
    <LocaleProvider initialLocale={locale}>
      <UiGuideTooltip />
      {showButton ? (
        <button
          type="button"
          data-ui-guide="knowledge.edit"
          aria-describedby="existing-description"
        >
          Edit
        </button>
      ) : null}
    </LocaleProvider>
  );
}

function renderGuide(locale: "en" | "zh" = "en") {
  return render(guideContent(locale));
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

  it("does not pin mouse-click focus after the pointer leaves", () => {
    renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });
    fireEvent.pointerOver(button);
    fireEvent.pointerDown(button);
    fireEvent.focusIn(button);
    fireEvent.pointerOut(button, { relatedTarget: document.body });
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(button.getAttribute("aria-describedby")).toBe(
      "existing-description",
    );
  });

  it("clears a missed leave event when a fast pointer move reaches empty space", () => {
    renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });
    fireEvent.pointerOver(button);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.pointerMove(document.body);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.pointerMove(button);
    expect(screen.getByRole("tooltip")).toBeTruthy();
  });

  it.each(["scroll", "blur", "resize", "pointercancel", "leave-window"])(
    "dismisses help on %s",
    (event) => {
      renderGuide();
      const button = screen.getByRole("button", { name: "Edit" });
      fireEvent.pointerOver(button);
      if (event === "scroll") fireEvent.scroll(document.body);
      else if (event === "blur") fireEvent.blur(window);
      else if (event === "resize") fireEvent.resize(window);
      else if (event === "pointercancel") fireEvent.pointerCancel(button);
      else fireEvent.pointerOut(document.body, { relatedTarget: null });
      expect(screen.queryByRole("tooltip")).toBeNull();
      expect(button.getAttribute("aria-describedby")).toBe(
        "existing-description",
      );
    },
  );

  it("clears help when the owning workspace route changes", () => {
    const view = renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });
    fireEvent.focusIn(button);
    route.pathname = "/student/groups/another-group";
    view.rerender(guideContent());
    expect(button.isConnected).toBe(true);
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(button.getAttribute("aria-describedby")).toBe(
      "existing-description",
    );
  });

  it("clears help when a control disappears without a pointer event", async () => {
    const view = renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });
    fireEvent.pointerOver(button);
    view.rerender(guideContent("en", false));
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
    expect(button.getAttribute("aria-describedby")).toBe(
      "existing-description",
    );
  });

  it("keeps opt-in touch help toggleable and clears it on an outside tap", () => {
    renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });
    button.dataset.uiGuideTouch = "true";
    const tap = () => {
      fireEvent.pointerDown(button, { pointerType: "touch" });
      fireEvent.pointerUp(button, { pointerType: "touch" });
      fireEvent.click(button);
    };
    tap();
    expect(screen.getByRole("tooltip")).toBeTruthy();
    tap();
    expect(screen.queryByRole("tooltip")).toBeNull();
    tap();
    fireEvent.pointerDown(document.body, { pointerType: "touch" });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("keeps keyboard help available after mouse use and dismisses it with Escape", () => {
    renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });
    fireEvent.pointerDown(document.body);
    fireEvent.keyDown(document, { key: "Tab" });
    fireEvent.focusIn(button);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});
