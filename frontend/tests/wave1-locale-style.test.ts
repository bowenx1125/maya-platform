import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { statusLabel, t } from "../lib/i18n";

describe("Wave 1A locale and V2 style boundary", () => {
  it("keeps English-first copy translatable without changing business state", () => {
    expect(t("publish", "en")).toBe("Publish version");
    expect(t("publish", "zh")).toBe("发布版本");
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
});
