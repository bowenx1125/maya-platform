import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UiGuideTooltip } from "../components/ui-guide-tooltip";

const route = vi.hoisted(() => ({ pathname: "/student/workspace" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.pathname }));
const originalGetBoundingClientRect =
  HTMLElement.prototype.getBoundingClientRect;

beforeEach(() => {
  route.pathname = "/student/workspace";
});
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
  vi.restoreAllMocks();
  if (originalInnerWidth)
    Object.defineProperty(window, "innerWidth", originalInnerWidth);
  if (originalInnerHeight)
    Object.defineProperty(window, "innerHeight", originalInnerHeight);
});

function mockTooltipMeasurement(width: number, height: number) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      if (this.getAttribute("role") === "tooltip") {
        return {
          left: 0,
          right: width,
          top: 0,
          bottom: height,
          width,
          height,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      }
      return originalGetBoundingClientRect.call(this);
    },
  );
}

function guideContent(showButton = true) {
  return (
    <>
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
    </>
  );
}

function renderGuide() {
  return render(guideContent());
}

describe("workspace UI guide tooltip", () => {
  it("does not show a hover tip on pressable controls", () => {
    renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });

    fireEvent.pointerOver(button, {
      pointerType: "mouse",
      clientX: 32,
      clientY: 48,
    });

    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(button.getAttribute("aria-describedby")).toBe(
      "existing-description",
    );
  });

  it("follows the pointer on labels and restores an existing description on leave", () => {
    render(
      <>
        <UiGuideTooltip />
        <label
          data-ui-guide="knowledge.edit"
          aria-describedby="existing-description"
        >
          Edit field
        </label>
      </>,
    );
    const label = screen.getByText("Edit field");

    fireEvent.pointerOver(label, {
      pointerType: "mouse",
      clientX: 32,
      clientY: 48,
    });

    expect(screen.getByRole("tooltip").textContent).toContain(
      "Markdown editor",
    );
    expect(label.getAttribute("aria-describedby")).toBe(
      "existing-description maya-ui-guide-tooltip",
    );

    fireEvent.pointerOut(label, { relatedTarget: document.body });

    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(label.getAttribute("aria-describedby")).toBe("existing-description");
  });

  it.each(["focus", "pointer", "touch"])(
    "clears %s help when navigation removes its target without a leave event",
    async (input) => {
      const view = render(
        <>
          <UiGuideTooltip />
          <label
            data-ui-guide="knowledge.edit"
            aria-describedby="existing-description"
          >
            Edit field
          </label>
        </>,
      );
      const label = screen.getByText("Edit field");
      if (input === "focus") fireEvent.focusIn(label);
      else if (input === "touch") {
        fireEvent.pointerUp(label, { pointerType: "touch" });
      } else {
        fireEvent.pointerOver(label, { pointerType: "mouse" });
      }
      expect(screen.getByRole("tooltip")).toBeTruthy();

      view.rerender(
        <>
          <UiGuideTooltip />
          <h1>Classroom stage</h1>
        </>,
      );

      await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
      expect(label.isConnected).toBe(false);
      expect(label.getAttribute("aria-describedby")).toBe(
        "existing-description",
      );
      fireEvent.pointerMove(document.body, { pointerType: "mouse" });
      fireEvent.scroll(document);
      fireEvent.resize(window);
      expect(screen.queryByRole("tooltip")).toBeNull();
    },
  );

  it("clears help when its focused input is removed but the guide label remains", async () => {
    const view = render(
      <>
        <UiGuideTooltip />
        <label data-ui-guide="voice.consent">
          <input
            type="checkbox"
            aria-label="Voice consent"
            aria-describedby="existing-description"
          />
          Voice consent
        </label>
      </>,
    );
    const checkbox = screen.getByRole("checkbox", { name: "Voice consent" });
    const label = checkbox.closest("label");
    fireEvent.focusIn(checkbox);
    expect(screen.getByRole("tooltip")).toBeTruthy();

    view.rerender(
      <>
        <UiGuideTooltip />
        <label data-ui-guide="voice.consent">Voice consent</label>
      </>,
    );

    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
    expect(label?.isConnected).toBe(true);
    expect(checkbox.getAttribute("aria-describedby")).toBe(
      "existing-description",
    );
    fireEvent.pointerOver(label!, { pointerType: "mouse" });
    expect(screen.getByRole("tooltip")).toBeTruthy();
    expect(label?.getAttribute("aria-describedby")).toBe(
      "maya-ui-guide-tooltip",
    );
  });

  it("shows help on keyboard focus", () => {
    renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });

    fireEvent.focusIn(button);

    expect(screen.getByRole("tooltip").textContent).toContain(
      "Markdown editor",
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
    render(
      <>
        <UiGuideTooltip />
        <label data-ui-guide="knowledge.edit">Edit field</label>
      </>,
    );
    const label = screen.getByText("Edit field");
    fireEvent.pointerOver(label);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.pointerMove(document.body);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.pointerMove(label);
    expect(screen.getByRole("tooltip")).toBeTruthy();
  });

  it.each(["scroll", "blur", "resize", "pointercancel", "leave-window"])(
    "dismisses help on %s",
    (event) => {
      renderGuide();
      const button = screen.getByRole("button", { name: "Edit" });
      fireEvent.focusIn(button);
      expect(screen.getByRole("tooltip")).toBeTruthy();
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
    fireEvent.focusIn(button);
    view.rerender(guideContent(false));
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

  it("keeps pointer help clear of long import instructions", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1280,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 720,
    });
    render(
      <>
        <UiGuideTooltip />
        <label data-ui-guide="knowledge.importFile">Import a file</label>
        <p>
          Upload Markdown, PDF, or Word. Maya converts files to Markdown for
          this library.
        </p>
      </>,
    );
    const label = screen.getByText("Import a file");
    label.getBoundingClientRect = () =>
      ({
        left: 308,
        right: 1180,
        top: 190,
        bottom: 234,
        width: 872,
        height: 44,
        x: 308,
        y: 190,
        toJSON: () => ({}),
      }) as DOMRect;
    const instructions = screen.getByText(/Maya converts files/);
    instructions.getBoundingClientRect = () =>
      ({
        left: 308,
        right: 1180,
        top: 272,
        bottom: 340,
        width: 872,
        height: 68,
        x: 308,
        y: 272,
        toJSON: () => ({}),
      }) as DOMRect;

    mockTooltipMeasurement(280, 70);
    fireEvent.pointerOver(label, {
      pointerType: "mouse",
      clientX: 663,
      clientY: 230,
    });
    const tooltip = screen.getByRole("tooltip");

    const left = Number.parseFloat(tooltip.style.left);
    const top = Number.parseFloat(tooltip.style.top);
    const overlaps = (rect: DOMRect) =>
      left < rect.right &&
      left + 280 > rect.left &&
      top < rect.bottom &&
      top + 70 > rect.top;
    expect(overlaps(label.getBoundingClientRect())).toBe(false);
    expect(overlaps(instructions.getBoundingClientRect())).toBe(false);
  });

  it("describes the focused control when help is marked on its label", () => {
    render(
      <>
        <UiGuideTooltip />
        <label data-ui-guide="voice.consent">
          <input
            type="checkbox"
            aria-label="Voice consent"
            aria-describedby="existing-description"
          />
          Voice consent
        </label>
      </>,
    );
    const checkbox = screen.getByRole("checkbox", { name: "Voice consent" });
    const label = checkbox.closest("label")!;

    fireEvent.focusIn(checkbox);

    expect(screen.getByRole("tooltip").textContent).toContain(
      "permission to upload and clone",
    );
    expect(checkbox.getAttribute("aria-describedby")).toBe(
      "existing-description maya-ui-guide-tooltip",
    );
    expect(label?.hasAttribute("aria-describedby")).toBe(false);

    fireEvent.pointerOver(checkbox, {
      pointerType: "mouse",
      clientX: 40,
      clientY: 50,
    });

    expect(checkbox.getAttribute("aria-describedby")).toBe(
      "existing-description maya-ui-guide-tooltip",
    );
    expect(label?.hasAttribute("aria-describedby")).toBe(false);

    fireEvent.pointerOut(checkbox, { relatedTarget: document.body });
    fireEvent.focusOut(checkbox, { relatedTarget: document.body });
    expect(checkbox.getAttribute("aria-describedby")).toBe(
      "existing-description",
    );
  });

  it("moves the description from a hovered label to its keyboard-focused control", () => {
    render(
      <>
        <UiGuideTooltip />
        <label data-ui-guide="voice.consent">
          <input
            type="checkbox"
            aria-label="Voice consent transition"
            aria-describedby="existing-description"
          />
          Voice consent
        </label>
      </>,
    );
    const checkbox = screen.getByRole("checkbox", {
      name: "Voice consent transition",
    });
    const label = checkbox.closest("label")!;

    fireEvent.pointerOver(label, { pointerType: "mouse" });
    expect(label.getAttribute("aria-describedby")).toBe(
      "maya-ui-guide-tooltip",
    );

    fireEvent.keyDown(document, { key: "Tab" });
    fireEvent.focusIn(checkbox);

    expect(screen.getByRole("tooltip")).toBeTruthy();
    expect(checkbox.getAttribute("aria-describedby")).toBe(
      "existing-description maya-ui-guide-tooltip",
    );
    expect(label.hasAttribute("aria-describedby")).toBe(false);

    fireEvent.pointerOver(checkbox, {
      pointerType: "mouse",
      clientX: 40,
      clientY: 50,
    });
    expect(checkbox.getAttribute("aria-describedby")).toBe(
      "existing-description maya-ui-guide-tooltip",
    );
    expect(label.hasAttribute("aria-describedby")).toBe(false);
  });

  it("pins opt-in touch help until the same guided control is tapped again", () => {
    renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });
    button.dataset.uiGuideTouch = "true";

    fireEvent.pointerUp(button, { pointerType: "touch" });

    expect(screen.getByRole("tooltip").textContent).toContain(
      "Markdown editor",
    );

    fireEvent.pointerUp(button, { pointerType: "touch" });

    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("shows a help ? button's own text on hover, keeps it on click, and on tap", () => {
    render(
      <>
        <UiGuideTooltip />
        <button
          type="button"
          aria-label="temperature: 随机性"
          data-ui-guide="debate.llmParam"
          data-ui-guide-text={"随机性：越高越活越随意。\n建议：0.6–0.8。"}
          data-ui-guide-hover="true"
        >
          ?
        </button>
      </>,
    );
    const help = screen.getByRole("button", { name: /temperature/ });

    fireEvent.pointerOver(help, {
      pointerType: "mouse",
      clientX: 10,
      clientY: 10,
    });
    expect(screen.getByRole("tooltip").textContent).toContain("随机性");
    expect(screen.getByRole("tooltip").textContent).toContain("建议：0.6–0.8");

    fireEvent.pointerDown(help, { pointerType: "mouse" });
    fireEvent.click(help);
    expect(screen.getByRole("tooltip").textContent).toContain("随机性");

    fireEvent.pointerOut(help, { relatedTarget: document.body });
    expect(screen.queryByRole("tooltip")).toBeNull();

    fireEvent.pointerUp(help, { pointerType: "touch" });
    expect(screen.getByRole("tooltip").textContent).toContain("随机性");
  });

  it("does not show touch help on pressables without data-ui-guide-touch", () => {
    renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });

    fireEvent.pointerUp(button, { pointerType: "touch" });

    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("shows touch help on non-pressable guides without a special touch marker", () => {
    render(
      <>
        <UiGuideTooltip />
        <label data-ui-guide="knowledge.edit">Edit field</label>
      </>,
    );
    const label = screen.getByText("Edit field");

    fireEvent.pointerUp(label, { pointerType: "touch" });

    expect(screen.getByRole("tooltip").textContent).toContain(
      "Markdown editor",
    );
  });

  it("avoids covering nearby controls when a guided control receives focus", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1280,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 720,
    });
    render(
      <>
        <UiGuideTooltip />
        <button type="button" data-ui-guide="knowledge.edit">
          Focused control
        </button>
        <button type="button">Neighbor control</button>
      </>,
    );
    const [button, neighbor] = screen.getAllByRole("button");
    button.getBoundingClientRect = () =>
      ({
        left: 1146,
        right: 1182,
        top: 588,
        bottom: 624,
        width: 36,
        height: 36,
        x: 1146,
        y: 588,
        toJSON: () => ({}),
      }) as DOMRect;
    neighbor.getBoundingClientRect = () =>
      ({
        left: 1150,
        right: 1186,
        top: 630,
        bottom: 666,
        width: 36,
        height: 36,
        x: 1150,
        y: 630,
        toJSON: () => ({}),
      }) as DOMRect;

    mockTooltipMeasurement(180, 40);
    fireEvent.focusIn(button);
    const tooltip = screen.getByRole("tooltip");
    const left = Number.parseFloat(tooltip.style.left);
    const top = Number.parseFloat(tooltip.style.top);
    const overlaps = (rect: DOMRect) =>
      left < rect.right &&
      left + 180 > rect.left &&
      top < rect.bottom &&
      top + 40 > rect.top;
    expect(overlaps(button.getBoundingClientRect())).toBe(false);
    expect(overlaps(neighbor.getBoundingClientRect())).toBe(false);
  });

  it("avoids covering nearby controls when a guided label is hovered", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1280,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 720,
    });
    render(
      <>
        <UiGuideTooltip />
        <label data-ui-guide="knowledge.edit">Hovered control</label>
        <button type="button">Neighbor control</button>
      </>,
    );
    const label = screen.getByText("Hovered control");
    const neighbor = screen.getByRole("button");
    label.getBoundingClientRect = () =>
      ({
        left: 490,
        right: 530,
        top: 490,
        bottom: 530,
        width: 40,
        height: 40,
        x: 490,
        y: 490,
        toJSON: () => ({}),
      }) as DOMRect;
    neighbor.getBoundingClientRect = () =>
      ({
        left: 510,
        right: 550,
        top: 510,
        bottom: 550,
        width: 40,
        height: 40,
        x: 510,
        y: 510,
        toJSON: () => ({}),
      }) as DOMRect;

    mockTooltipMeasurement(180, 40);
    fireEvent.pointerOver(label, {
      pointerType: "mouse",
      clientX: 500,
      clientY: 500,
    });
    const tooltip = screen.getByRole("tooltip");

    const left = Number.parseFloat(tooltip.style.left);
    const top = Number.parseFloat(tooltip.style.top);
    const overlaps = (rect: DOMRect) =>
      left < rect.right &&
      left + 180 > rect.left &&
      top < rect.bottom &&
      top + 40 > rect.top;
    expect(overlaps(label.getBoundingClientRect())).toBe(false);
    expect(overlaps(neighbor.getBoundingClientRect())).toBe(false);
  });

  it("avoids covering neighboring file text when a row action receives focus", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1280,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 720,
    });
    render(
      <>
        <UiGuideTooltip />
        <strong>Upper left title</strong>
        <strong>Upper right title</strong>
        <span>Left ready</span>
        <button type="button" data-ui-guide="knowledge.edit">
          Edit
        </button>
        <span>Right ready</span>
        <strong>Neighbor file title</strong>
      </>,
    );
    const button = screen.getByRole("button", { name: "Edit" });
    button.getBoundingClientRect = () =>
      ({
        left: 649,
        right: 677,
        top: 216,
        bottom: 244,
        width: 28,
        height: 28,
        x: 649,
        y: 216,
        toJSON: () => ({}),
      }) as DOMRect;
    const textRects = [
      {
        element: screen.getByText("Upper left title"),
        left: 318,
        right: 737,
        top: 167,
        bottom: 191,
      },
      {
        element: screen.getByText("Upper right title"),
        left: 766,
        right: 1185,
        top: 167,
        bottom: 191,
      },
      {
        element: screen.getByText("Left ready"),
        left: 318,
        right: 379,
        top: 217,
        bottom: 244,
      },
      {
        element: screen.getByText("Right ready"),
        left: 766,
        right: 830,
        top: 217,
        bottom: 244,
      },
      {
        element: screen.getByText("Neighbor file title"),
        left: 766,
        right: 1185,
        top: 269,
        bottom: 293,
      },
    ];
    for (const { element, ...rect } of textRects) {
      element.getBoundingClientRect = () =>
        ({
          ...rect,
          width: rect.right - rect.left,
          height: rect.bottom - rect.top,
          x: rect.left,
          y: rect.top,
          toJSON: () => ({}),
        }) as DOMRect;
    }

    mockTooltipMeasurement(268, 35);
    fireEvent.focusIn(button);
    const tooltip = screen.getByRole("tooltip");

    const left = Number.parseFloat(tooltip.style.left);
    const top = Number.parseFloat(tooltip.style.top);
    expect(
      textRects.some(
        ({
          left: textLeft,
          right: textRight,
          top: textTop,
          bottom: textBottom,
        }) =>
          left < textRight &&
          left + 268 > textLeft &&
          top < textBottom &&
          top + 35 > textTop,
      ),
    ).toBe(false);
  });

  it("clears help on scroll and resize, then recalculates on fresh keyboard focus", () => {
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
    button.getBoundingClientRect = buttonRect;

    mockTooltipMeasurement(100, 30);
    fireEvent.focusIn(button);
    const tooltipElement = screen.getByRole("tooltip");
    expect(tooltipElement.style.top).toBe("140px");

    targetTop = 50;
    fireEvent.scroll(document);
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(button.getAttribute("aria-describedby")).toBe(
      "existing-description",
    );

    fireEvent.focusIn(button);
    expect(screen.getByRole("tooltip").style.top).toBe("90px");

    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 150,
    });
    fireEvent.resize(window);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.focusIn(button);
    expect(screen.getByRole("tooltip").style.left).toBe("42px");
  });
});
