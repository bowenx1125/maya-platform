import { describe, expect, it } from "vitest";

import { chatStreamLanguage, resolveInitialLocale } from "../lib/i18n";

describe("initial locale", () => {
  it("prefers an explicit en or zh cookie over the browser language", () => {
    expect(resolveInitialLocale("zh", "en-US,en;q=0.9")).toBe("zh");
    expect(resolveInitialLocale("en", "zh-CN,zh;q=0.9")).toBe("en");
  });

  it("follows Accept-Language when the cookie is missing or not a supported locale", () => {
    expect(resolveInitialLocale(undefined, "zh-CN,zh;q=0.9,en;q=0.8")).toBe(
      "zh",
    );
    expect(resolveInitialLocale(null, "en-US,en;q=0.9")).toBe("en");
    expect(resolveInitialLocale("fr", "zh-Hans;q=0.9,en;q=0.4")).toBe("zh");
    expect(resolveInitialLocale("", "zh-TW")).toBe("zh");
    expect(resolveInitialLocale(undefined, "en;q=0.5, zh-CN;q=0.9")).toBe("zh");
    expect(resolveInitialLocale(undefined, "fr,de;q=0.8")).toBe("en");
    expect(resolveInitialLocale(undefined, null)).toBe("en");
  });
});

describe("chat stream language", () => {
  it("keeps supported values to zh-CN and en", () => {
    expect(chatStreamLanguage("en", "Hello")).toBe("en");
    expect(chatStreamLanguage("zh", "Hello")).toBe("zh-CN");
    expect(chatStreamLanguage("en", "陶罐在哪里？")).toBe("zh-CN");
    expect(chatStreamLanguage("zh", "陶罐在哪里？")).toBe("zh-CN");
    expect(chatStreamLanguage("en", "The 道 is discussed here")).toBe("en");
    expect(chatStreamLanguage("en", "See [S1].")).toBe("en");
  });
});
