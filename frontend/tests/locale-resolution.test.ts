import { describe, expect, it } from "vitest";

import { chatStreamLanguage } from "../lib/i18n";

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
