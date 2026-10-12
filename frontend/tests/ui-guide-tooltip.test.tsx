import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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

  it.each(["focus", "pointer", "touch"])(
    "clears %s help when navigation removes its target without a leave event",
    async (input) => {
      const view = renderGuide();
      const button = screen.getByRole("button", { name: "Edit" });
      if (input === "focus") fireEvent.focusIn(button);
      else if (input === "touch") {
        fireEvent.pointerUp(button, { pointerType: "touch" });
      } else {
        fireEvent.pointerOver(button, { pointerType: "mouse" });
      }
      expect(screen.getByRole("tooltip")).toBeTruthy();

      view.rerender(
        <LocaleProvider initialLocale="en">
          <UiGuideTooltip />
          <h1>Classroom stage</h1>
        </LocaleProvider>,
      );

      await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
      expect(button.isConnected).toBe(false);
      expect(button.getAttribute("aria-describedby")).toBe(
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
      <LocaleProvider initialLocale="en">
        <UiGuideTooltip />
        <label data-ui-guide="voice.consent">
          <input
            type="checkbox"
            aria-label="Voice consent"
            aria-describedby="existing-description"
          />
          Voice consent
        </label>
      </LocaleProvider>,
    );
    const checkbox = screen.getByRole("checkbox", { name: "Voice consent" });
    const label = checkbox.closest("label");
    fireEvent.focusIn(checkbox);
    expect(screen.getByRole("tooltip")).toBeTruthy();

    view.rerender(
      <LocaleProvider initialLocale="en">
        <UiGuideTooltip />
        <label data-ui-guide="voice.consent">Voice consent</label>
      </LocaleProvider>,
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
      <LocaleProvider initialLocale="en">
        <UiGuideTooltip />
        <label data-ui-guide="knowledge.importFile">Import a file</label>
        <p>
          Upload Markdown, PDF, or Word. Maya converts files to Markdown for
          this library.
        </p>
      </LocaleProvider>,
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

    fireEvent.pointerOver(label, {
      pointerType: "mouse",
      clientX: 663,
      clientY: 230,
    });
    const tooltip = screen.getByRole("tooltip");
    tooltip.getBoundingClientRect = () =>
      ({
        left: 0,
        right: 280,
        top: 0,
        bottom: 70,
        width: 280,
        height: 70,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect;
    fireEvent.resize(window);

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

  it("describes the focused control when help is marked on its label", () => {
    render(
      <LocaleProvider initialLocale="en">
        <UiGuideTooltip />
        <label data-ui-guide="voice.consent">
          <input
            type="checkbox"
            aria-label="Voice consent"
            aria-describedby="existing-description"
          />
          Voice consent
        </label>
      </LocaleProvider>,
    );
    const checkbox = screen.getByRole("checkbox", { name: "Voice consent" });
    const label = checkbox.closest("label");

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

  it.each([
    {
      guide: "agent.uploadMarkdown",
      expectedText: "next Agent draft revision",
      description: null,
      inputGuide: false,
    },
    {
      guide: "agent.uploadEvidence",
      expectedText: "Agent evidence",
      description: "knowledge-import-help",
      inputGuide: false,
    },
    {
      guide: "knowledge.importFile",
      expectedText: "converted to Markdown",
      description: "knowledge-import-formats",
      inputGuide: false,
    },
    {
      guide: "voice.uploadSample",
      expectedText: "audio sample",
      description: null,
      inputGuide: true,
    },
  ])(
    "shows upload guidance for $guide",
    ({ guide, expectedText, description, inputGuide }) => {
      const input = (
        <input
          type="file"
          aria-label="Upload"
          aria-describedby={description ?? undefined}
          data-ui-guide={inputGuide ? guide : undefined}
        />
      );
      render(
        <LocaleProvider initialLocale="en">
          <UiGuideTooltip />
          {inputGuide ? (
            input
          ) : (
            <label data-ui-guide={guide}>Upload{input}</label>
          )}
        </LocaleProvider>,
      );

      const upload = screen.getByLabelText("Upload");
      fireEvent.focusIn(upload);

      expect(screen.getByRole("tooltip").textContent).toContain(expectedText);
      expect(upload.getAttribute("aria-describedby")).toBe(
        description
          ? `${description} maya-ui-guide-tooltip`
          : "maya-ui-guide-tooltip",
      );

      fireEvent.focusOut(upload, { relatedTarget: document.body });
      expect(upload.getAttribute("aria-describedby")).toBe(description);
    },
  );

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

  it("shows touch help on guided controls without a special touch marker", () => {
    renderGuide();
    const button = screen.getByRole("button", { name: "Edit" });

    fireEvent.pointerUp(button, { pointerType: "touch" });

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
      <LocaleProvider initialLocale="en">
        <UiGuideTooltip />
        <button type="button" data-ui-guide="knowledge.edit">
          Focused control
        </button>
        <button type="button">Neighbor control</button>
      </LocaleProvider>,
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

    fireEvent.focusIn(button);
    const tooltip = screen.getByRole("tooltip");
    tooltip.getBoundingClientRect = () =>
      ({
        left: 0,
        right: 180,
        top: 0,
        bottom: 40,
        width: 180,
        height: 40,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect;
    fireEvent.resize(window);

    expect(Number.parseFloat(tooltip.style.top)).toBeLessThan(588);
  });

  it("avoids covering nearby controls when a guided control is hovered", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1280,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 720,
    });
    render(
      <LocaleProvider initialLocale="en">
        <UiGuideTooltip />
        <button type="button" data-ui-guide="knowledge.edit">
          Hovered control
        </button>
        <button type="button">Neighbor control</button>
      </LocaleProvider>,
    );
    const [button, neighbor] = screen.getAllByRole("button");
    button.getBoundingClientRect = () =>
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

    fireEvent.pointerOver(button, {
      pointerType: "mouse",
      clientX: 500,
      clientY: 500,
    });
    const tooltip = screen.getByRole("tooltip");
    tooltip.getBoundingClientRect = () =>
      ({
        left: 0,
        right: 180,
        top: 0,
        bottom: 40,
        width: 180,
        height: 40,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect;
    fireEvent.pointerMove(button, {
      pointerType: "mouse",
      clientX: 500,
      clientY: 500,
    });

    const left = Number.parseFloat(tooltip.style.left);
    const top = Number.parseFloat(tooltip.style.top);
    expect(
      left + 180 <= 510 || left >= 550 || top + 40 <= 510 || top >= 550,
    ).toBe(true);
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
      <LocaleProvider initialLocale="en">
        <UiGuideTooltip />
        <strong>Upper left title</strong>
        <strong>Upper right title</strong>
        <span>Left ready</span>
        <button type="button" data-ui-guide="knowledge.edit">
          Edit
        </button>
        <span>Right ready</span>
        <strong>Neighbor file title</strong>
      </LocaleProvider>,
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

    fireEvent.focusIn(button);
    const tooltip = screen.getByRole("tooltip");
    tooltip.getBoundingClientRect = () =>
      ({
        left: 0,
        right: 268,
        top: 0,
        bottom: 35,
        width: 268,
        height: 35,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect;
    fireEvent.resize(window);

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
