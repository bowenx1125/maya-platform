import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { unlayer } from "./unlayer";

const style = document.createElement("style");
style.textContent = unlayer(
  readFileSync(
    resolve(process.cwd(), "components/debate/setup/debate-setup.module.css"),
    "utf8",
  ),
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

  it("lets long debate titles wrap inside the topic column without clipping", () => {
    document.head.append(style);
    const rules = Array.from(style.sheet!.cssRules);
    const title = rules.find(
      (rule) => (rule as CSSStyleRule).selectorText === ".debateCard h2",
    ) as CSSStyleRule;
    const topic = rules.find(
      (rule) =>
        (rule as CSSStyleRule).selectorText === ".debateCard > div:first-child",
    ) as CSSStyleRule;
    expect(title.style.getPropertyValue("min-width")).toBe("0px");
    expect(title.style.getPropertyValue("overflow-wrap")).toBe("anywhere");
    expect(title.style.getPropertyValue("max-width")).toBe("100%");
    expect(topic.style.getPropertyValue("min-width")).toBe("0px");
  });

  it("keeps a single action separator and no extra horizontal rules on rows", () => {
    const { actions, mobileRule } = layoutRules();
    expect(actions.getPropertyValue("border-left")).toBe(
      "1px solid var(--line, #dedee3)",
    );
    document.head.append(style);
    const rules = Array.from(style.sheet!.cssRules);
    const rowCard = rules.find(
      (rule) =>
        (rule as CSSStyleRule).selectorText === ".debateRow > .debateCard",
    ) as CSSStyleRule;
    expect(rowCard.style.getPropertyValue("border-top-width") || "0px").toMatch(
      /^0/,
    );
    expect(rowCard.style.getPropertyValue("border") || "0px").toMatch(/^0/);
    const mobileActions = mobileRule(".debateActions");
    expect(mobileActions.getPropertyValue("border-left")).toBe("0px");
    expect(mobileActions.getPropertyValue("border-top")).toBe("0px");
  });
});
