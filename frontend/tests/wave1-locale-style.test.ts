import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { errorCopyFor, localizeError, statusLabel, t } from "../lib/i18n";

describe("Wave 1A copy and V2 style boundary", () => {
  it.each(["invalid_utf8", "empty_markdown", "invalid_control_chars"])(
    "gives Markdown-specific recovery for %s",
    (reason) => {
      for (const code of [
        "knowledge_import_invalid",
        "file_operation_failed",
      ]) {
        const message = localizeError({
          code,
          status: 422,
          details: { reason },
        });
        expect(message).toContain("UTF-8 Markdown");
        expect(message).not.toMatch(/PDF|Word|OCR/);
      }
    },
  );

  it.each(["invalid_pdf", "invalid_docx", "invalid_filename", "invalid"])(
    "keeps format-neutral import guidance for %s",
    (reason) => {
      expect(
        localizeError({
          code: "knowledge_import_invalid",
          details: { reason },
        }),
      ).toBe(t("knowledgeImportInvalid"));
    },
  );

  it("shows the actual authentication recovery delay in the existing error text", () => {
    const error = {
      code: "auth_rate_limited",
      status: 429,
      details: { retry_after_seconds: 37 },
    };
    expect(localizeError(error)).toContain("37 seconds");
    expect(
      localizeError({
        code: "auth_login_queued",
        status: 429,
        details: { position: 4, retry_after_seconds: 2 },
      }),
    ).toBe("Waiting to enter. 4 people are ahead of you.");
    expect(
      localizeError({
        code: "auth_login_queued",
        status: 429,
        details: { position: 0 },
      }),
    ).toBe("Waiting to enter. You are next.");
    expect(localizeError({ code: "provider_unavailable", status: 503 })).toBe(
      "A platform capability is temporarily unavailable.",
    );
    const malformed = Object.assign(new Error("Please try again later."), {
      ...error,
      details: { retry_after_seconds: "not-a-delay" },
    });
    // A malformed delay falls back to the code's catalog copy, not the raw message.
    expect(localizeError(malformed)).toBe(
      errorCopyFor("auth_rate_limited") ?? "<missing copy>",
    );
  });

  it("keeps platform copy apart from business state", () => {
    expect(t("publish")).toBe("Publish");
    expect(statusLabel("stale_revision")).toBe("stale revision");
    expect(statusLabel("published")).toBe(t("statusPublished"));
    expect(localizeError({ code: "agent_name_conflict", status: 409 })).toBe(
      t("errorAgentNameConflict"),
    );
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

  it("keeps the display serif on workspace headings", () => {
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
    // Sign-in moved to Arcade type (proposal 38 v3, approved 2026-10-27), so
    // its tagline and welcome no longer carry the serif.
    expect(css).toMatch(
      /\.section-card-header h2\s*\{[\s\S]*?font-family:\s*var\(--display-serif\)/,
    );
  });
  it("keeps the debate setup section-card-header free of a hairline divider", () => {
    // The setup cards are Tailwind CreateCards now (CSS Module deleted in
    // the Debates final); they never render the shared hairline header.
    const source = readFileSync(
      resolve(process.cwd(), "components/debate/setup/create-card.tsx"),
      "utf8",
    );
    expect(source).not.toMatch(/section-card-header/);
    expect(source).not.toMatch(/border-b(?:-|\s|")/);
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
