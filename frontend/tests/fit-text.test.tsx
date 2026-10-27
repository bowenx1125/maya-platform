import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FitTitle } from "../components/fit-title";
import {
  FIT_TEXT_SCALES,
  initialScaleIndex,
  pickFitScale,
  titleWidthUnits,
} from "../lib/fit-text";

describe("fit-text logic", () => {
  it("counts CJK as two Latin units", () => {
    expect(titleWidthUnits("abc")).toBe(3);
    expect(titleWidthUnits("朱熹")).toBe(4);
    expect(titleWidthUnits("Zhu 熹")).toBe(6);
  });

  it("keeps short titles at full size and steps long ones down", () => {
    expect(initialScaleIndex("Zhu Xi")).toBe(0);
    expect(initialScaleIndex("朱".repeat(40))).toBe(FIT_TEXT_SCALES.length - 1);
    const mid = initialScaleIndex("a".repeat(45));
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(FIT_TEXT_SCALES.length - 1);
  });

  it("picks the largest scale that fits, from any start", () => {
    const fitsBelow = (limit: number) => (scale: number) => scale <= limit;
    for (let start = 0; start < FIT_TEXT_SCALES.length; start += 1) {
      expect(pickFitScale(fitsBelow(0.85), start)).toBe(0.85);
      expect(pickFitScale(fitsBelow(1), start)).toBe(1);
      // Nothing fits: smallest step, the clamp's ellipsis is the last resort.
      expect(pickFitScale(fitsBelow(0.1), start)).toBe(0.72);
    }
  });

  it("bounds the number of measurements", () => {
    let calls = 0;
    pickFitScale((scale) => {
      calls += 1;
      return scale <= 0.72;
    }, 0);
    expect(calls).toBeLessThanOrEqual(FIT_TEXT_SCALES.length);
  });
});

describe("FitTitle", () => {
  it("renders the full title and leaves short ones at full size", () => {
    render(<FitTitle text="Zhu Xi" />);
    const el = screen.getByText("Zhu Xi");
    expect(el.className).toBe("fit-title-text");
    expect(el.style.fontSize).toBe("");
  });

  it("shrinks a long zh title without layout (length fallback)", () => {
    const title =
      "朱熹理学与王阳明心学的比较研究：从格物致知到知行合一的思想演变";
    render(<FitTitle text={title} />);
    const el = screen.getByText(title);
    expect(el.textContent).toBe(title);
    expect(el.style.fontSize).toMatch(/em$/);
  });
});

describe("title buttons use FitTitle", () => {
  it("wraps a Studyform Agent/Team tile name in the fit span", async () => {
    const { VersionTile } = await import("../components/studyform-layout");
    render(
      <ul>
        <VersionTile
          name="Comparative Study of Confucian Ethics and Aristocratic Virtue"
          href="/x"
          label="V1.0"
          pending={false}
          deleteLabel="Delete"
        />
      </ul>,
    );
    const link = screen.getByRole("link", {
      name: "Comparative Study of Confucian Ethics and Aristocratic Virtue",
    });
    // Whole-card link is an absolute hit target; FitTitle sits on the card.
    const card = link.closest("li") ?? link.parentElement;
    expect(card?.querySelector(".fit-title-text")).not.toBeNull();
  });

  it("keeps the RAG/Knowledge row copy on the buttons' row", async () => {
    const fs = await import("node:fs");
    const css = fs.readFileSync(
      "components/knowledge/brainform-workspace.module.css",
      "utf8",
    );
    expect(css).toMatch(/\.rowCopy \{[^}]*flex: 1 1 0;/);
  });
});
