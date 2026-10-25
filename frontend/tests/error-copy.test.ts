import { describe, expect, it } from "vitest";

import errorCopy from "../lib/error-copy.json";
import { localizeError } from "../lib/i18n";

const catalog = errorCopy as {
  messages: Record<string, { en: string }>;
  codes: Record<string, string>;
};

describe("error copy catalog", () => {
  it("renders every catalogued code in English", () => {
    for (const [code, key] of Object.entries(catalog.codes)) {
      const message = catalog.messages[key];
      expect(message, code).toBeDefined();
      expect(localizeError({ code, status: 409 })).toBe(message.en);
    }
  });

  it("keeps specific copy ahead of the catalog", () => {
    expect(localizeError({ code: "internal_error" })).not.toBe(
      catalog.messages.generic?.en,
    );
    expect(Object.hasOwn(catalog.codes, "internal_error")).toBe(false);
  });

  it("still names an unknown code instead of a bare failure", () => {
    expect(localizeError({ code: "never_sent_code" })).toContain(
      "never_sent_code",
    );
  });
});
