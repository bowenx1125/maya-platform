import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { unlayer } from "./unlayer";

const style = document.createElement("style");
style.textContent = unlayer(
  readFileSync(
    resolve(process.cwd(), "components/avatar/avatar.module.css"),
    "utf8",
  ),
);

afterEach(() => style.remove());

describe("Avatar preview label layout", () => {
  it("wraps long preview names instead of hard single-line clipping", () => {
    document.head.append(style);
    const rule = Array.from(style.sheet!.cssRules).find(
      (entry) => (entry as CSSStyleRule).selectorText === ".previewLabel",
    ) as CSSStyleRule;
    expect(rule.style.getPropertyValue("white-space")).toBe("normal");
    expect(rule.style.getPropertyValue("overflow-wrap")).toBe("anywhere");
    expect(rule.style.getPropertyValue("-webkit-line-clamp")).toBe("2");
  });
});
