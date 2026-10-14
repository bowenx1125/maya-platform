import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

const style = document.createElement("style");
style.textContent = readFileSync(
  resolve(process.cwd(), "components/debate/setup/debate-setup.module.css"),
  "utf8",
);

function layoutRules() {
  document.head.append(style);
  const rules = Array.from(style.sheet!.cssRules);
  const actions = rules.find(
    (rule) => (rule as CSSStyleRule).selectorText === ".debateActions",
  ) as CSSStyleRule;
  const mobile = rules.find(
    (rule) => (rule as CSSMediaRule).conditionText === "(max-width: 640px)",
  ) as CSSMediaRule;
  const mobileRule = (selector: string) =>
    (
      Array.from(mobile.cssRules).find(
        (rule) => (rule as CSSStyleRule).selectorText === selector,
      ) as CSSStyleRule
    ).style;
  return { actions: actions.style, mobileRule };
}

afterEach(() => style.remove());

describe("Debates list narrow-screen layout", () => {
  it("moves actions below the topic and keeps button wrapping enabled", () => {
    const { actions, mobileRule } = layoutRules();
    expect(mobileRule(".debateRow").getPropertyValue("flex-wrap")).toBe("wrap");
    expect(
      mobileRule(".debateRow > .debateCard").getPropertyValue("flex-basis"),
    ).toBe("100%");
    expect(actions.getPropertyValue("flex-wrap")).toBe("wrap");
  });

  it("lets the action group shrink inside its margins without clipping controls", () => {
    const { actions, mobileRule } = layoutRules();
    const mobileActions = mobileRule(".debateActions");
    expect(mobileActions.getPropertyValue("flex-grow")).toBe("1");
    expect(mobileActions.getPropertyValue("flex-shrink")).toBe("1");
    expect(mobileActions.getPropertyValue("flex-basis")).toBe("0px");
    expect(mobileActions.getPropertyValue("min-width")).toBe("0px");
    expect(mobileActions.getPropertyValue("max-width")).toBe(
      "calc(100% - 32px)",
    );
    expect(mobileActions.getPropertyValue("margin")).toBe("0px 16px 12px");
    expect(mobileActions.getPropertyValue("padding-left")).toBe("0px");
    expect(mobileActions.getPropertyValue("border-left")).toBe("0px");
    expect(mobileActions.getPropertyValue("justify-content")).toBe(
      "flex-start",
    );
    expect(actions.getPropertyValue("overflow")).not.toMatch(/hidden|clip/);
    expect(mobileActions.getPropertyValue("overflow")).not.toMatch(
      /hidden|clip/,
    );
  });
});
