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

  it("keeps workspace system typography scoped and removes visible page-title styles", () => {
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");
    const workspace = readFileSync(
      resolve(process.cwd(), "components/workspace-appearance.module.css"),
      "utf8",
    );
    expect(css).not.toMatch(/Georgia|Times New Roman|Times,/);
    expect(css).not.toContain(".page-intro");
    expect(css).toMatch(/\.sr-only\s*\{[\s\S]*?position:\s*absolute/);
    expect(workspace).toMatch(/--font-ui:\s*-apple-system,/);
    expect(workspace).toMatch(/font-family:\s*var\(--font-ui\)/);
    expect(workspace).toMatch(/font-size:\s*16px/);
    expect(css).toMatch(/font-family:\s*\n\s*Inter,/);
  });

  it("keeps the display serif on the sign-in plate only", () => {
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");
    const theme = readFileSync(
      resolve(process.cwd(), "components/workspace-theme.module.css"),
      "utf8",
    );
    // Only the two sign-in headings use --display-serif; product surfaces use
    // the compact UI font and nowhere may invent a second serif stack.
    const declarations = [
      ...(css.match(/font-family:[^;]+;/g) ?? []),
      ...(theme.match(/font-family:[^;]+;/g) ?? []),
    ];
    const display = declarations.filter((rule) =>
      rule.includes("var(--display-serif)"),
    );
    expect(display).toHaveLength(2);
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
    expect(theme).not.toContain("var(--display-serif)");
    expect(css).not.toMatch(
      /\.section-card-header h2\s*\{[^}]*font-family:\s*var\(--display-serif\)/,
    );
  });
});
