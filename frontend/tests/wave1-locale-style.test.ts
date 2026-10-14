import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { localizeError, statusLabel, t } from "../lib/i18n";

describe("Wave 1A locale and V2 style boundary", () => {
  it("shows the actual authentication recovery delay in the existing error text", () => {
    const error = {
      code: "auth_rate_limited",
      status: 429,
      details: { retry_after_seconds: 37 },
    };
    expect(localizeError(error, "zh")).toBe(
      "登录或注册尝试过于频繁，请在 37 秒后重试。",
    );
    expect(localizeError(error, "en")).toContain("37 seconds");
    const malformed = Object.assign(new Error("Please try again later."), {
      ...error,
      details: { retry_after_seconds: "not-a-delay" },
    });
    expect(localizeError(malformed, "zh")).toBe("Please try again later.");
  });

  it("keeps English-first copy translatable without changing business state", () => {
    expect(t("publish", "en")).toBe("Publish");
    expect(t("publish", "zh")).toBe("发布");
    expect(statusLabel("stale_revision", "en")).toBe("stale revision");
    expect(statusLabel("stale_revision", "zh")).toBe("stale revision");
    expect(statusLabel("published", "zh")).toBe("已发布");
    expect(
      localizeError({ code: "agent_name_conflict", status: 409 }, "zh"),
    ).toBe("已有同名Agent，请换名字或先删除重复Agent。");
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

  it("keeps the display serif on the sign-in plate and workspace headings", () => {
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");
    const theme = readFileSync(
      resolve(process.cwd(), "components/workspace-theme.module.css"),
      "utf8",
    );
    // Sign-in and section headings share --display-serif; nowhere else may
    // invent a second serif stack.
    const declarations = [
      ...(css.match(/font-family:[^;]+;/g) ?? []),
      ...(theme.match(/font-family:[^;]+;/g) ?? []),
    ];
    const display = declarations.filter((rule) =>
      rule.includes("var(--display-serif)"),
    );
    expect(display.length).toBeGreaterThanOrEqual(3);
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
    expect(css).toMatch(
      /\.section-card-header h2\s*\{[\s\S]*?font-family:\s*var\(--display-serif\)/,
    );
  });
  it("keeps the debate setup section-card-header free of a hairline divider", () => {
    const css = readFileSync(
      resolve(
        process.cwd(),
        "components/debate/setup/create-section.module.css",
      ),
      "utf8",
    );
    // Must beat workspace-theme `.surface .section-card-header` (0,2,0) under
    // `.surface` — a bare `.section .section-card-header` alone is not enough.
    const rule = css.match(
      /:global\(\.surface\)\s*\.section\s*:global\(\.section-card-header\)\s*,[\s\S]*?\.section\s*:global\(\.section-card-header\)\s*\{[^}]*\}/,
    )?.[0];
    expect(rule).toBeDefined();
    expect(rule).toMatch(/:global\(\.surface\)\s*\.section\s*:global\(\.section-card-header\)/);
    expect(rule).not.toMatch(/border-bottom:\s*1px\s+solid/);
    expect(rule).toMatch(/border-bottom:\s*0/);
  });
  it("keeps hidden upload controls out of full-width input styling", () => {
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");
    const selector = css
      .match(/^input:not\([^\n]+/m)?.[0]
      .trim()
      .replace(/,$/, "");
    expect(selector).toBeDefined();
    expect(selector).toContain(":not(:where(.sr-only))");
    const upload = document.createElement("input");
    upload.type = "file";
    upload.className = "sr-only";
    expect(upload.matches(selector!)).toBe(false);
    const visible = document.createElement("input");
    expect(visible.matches(selector!)).toBe(true);
  });
});
