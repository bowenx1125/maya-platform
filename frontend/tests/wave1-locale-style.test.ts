import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { statusLabel, t } from "../lib/i18n";

describe("Wave 1A locale and V2 style boundary", () => {
  it("keeps English-first copy translatable without changing business state", () => {
    expect(t("publish", "en")).toBe("Publish");
    expect(t("publish", "zh")).toBe("发布");
    expect(statusLabel("stale_revision", "en")).toBe("stale revision");
    expect(statusLabel("stale_revision", "zh")).toBe("stale revision");
    expect(statusLabel("published", "zh")).toBe("已发布");
  });

  it("guards the compact V2 sans typography without a full visual snapshot", () => {
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");
    expect(css).not.toMatch(/Georgia|Times New Roman|Times,/);
    expect(css).toMatch(
      /\.page-intro h1\s*\{[\s\S]*font-size:\s*clamp\(2rem, 4vw, 3\.25rem\)/,
    );
    expect(css).toMatch(/font-family:\s*\n\s*Inter,/);
  });

  it("confines the display serif to the sign-in plate", () => {
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");
    // The academy sign-in is the one surface allowed a serif. It is declared
    // once, as --display-serif, so a second product surface cannot pick one up
    // by copying a font stack; the rest of the interface stays on Inter.
    const declarations = css.match(/font-family:[^;]+;/g) ?? [];
    const display = declarations.filter((rule) =>
      rule.includes("var(--display-serif)"),
    );
    expect(display).toHaveLength(2);
    // "ui-sans-serif" in the body stack is not a serif; a bare serif family
    // anywhere else would be.
    const stray = declarations.filter(
      (rule) =>
        !rule.includes("var(--display-serif)") &&
        /(?<![\w-])serif\b/.test(rule),
    );
    expect(stray).toEqual([]);
    expect(css).toMatch(
      /\.academy-tagline h1\s*\{[\s\S]*?font-family:\s*var\(--display-serif\)/,
    );
    expect(css).toMatch(
      /\.academy-welcome\s*\{[\s\S]*?font-family:\s*var\(--display-serif\)/,
    );
  });
});
