import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  LocaleProvider,
  LanguageSwitcher,
  useLocale,
  useT,
} from "../components/locale";
import {
  ALLOWED_IDENTICAL_TERMS,
  avatarTemplateLabel,
  localizeError,
  messages,
  statusLabel,
} from "../lib/i18n";

function LocaleProbe() {
  const { locale } = useLocale();
  const t = useT();
  return (
    <>
      <output data-testid="locale">{locale}</output>
      <input aria-label="draft" defaultValue="unsaved draft" />
      <span>{t("studentHome")}</span>
      <LanguageSwitcher />
    </>
  );
}

describe("Wave 1C presentation locale", () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    document.cookie = "maya_ui_locale=; Max-Age=0; Path=/";
    document.documentElement.lang = "en-US";
  });

  it("restores a saved locale, maps html lang, and switches without remounting children", () => {
    render(
      <LocaleProvider initialLocale="zh">
        <LocaleProbe />
      </LocaleProvider>,
    );

    expect(screen.getByTestId("locale").textContent).toBe("zh");
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(document.cookie).toContain("maya_ui_locale=zh");
    expect(screen.getByText("学生首页")).toBeTruthy();
    expect((screen.getByLabelText("draft") as HTMLInputElement).value).toBe(
      "unsaved draft",
    );

    fireEvent.click(screen.getByRole("button", { name: "切换到英文" }));
    expect(screen.getByTestId("locale").textContent).toBe("en");
    expect(document.documentElement.lang).toBe("en-US");
    expect(document.cookie).toContain("maya_ui_locale=en");
    expect(screen.getByText("Student home")).toBeTruthy();
    expect((screen.getByLabelText("draft") as HTMLInputElement).value).toBe(
      "unsaved draft",
    );
  });

  it("falls back to English for an invalid persisted value", () => {
    render(
      <LocaleProvider initialLocale={"fr"}>
        <LocaleProbe />
      </LocaleProvider>,
    );
    expect(screen.getByTestId("locale").textContent).toBe("en");
    expect(document.documentElement.lang).toBe("en-US");
    expect(document.cookie).toContain("maya_ui_locale=en");
  });

  it("keeps typed dictionaries equal, populated, and interpolation-safe", () => {
    const englishKeys = Object.keys(messages.en).sort();
    const chineseKeys = Object.keys(messages.zh).sort();
    expect(chineseKeys).toEqual(englishKeys);

    const placeholders = (value: string) =>
      [...value.matchAll(/\{([A-Za-z0-9_]+)\}/g)]
        .map((match) => match[1])
        .sort();
    const intentionallyEmpty = new Set(["debateControllerWaiting"]);
    for (const key of englishKeys) {
      const english = messages.en[key as keyof typeof messages.en];
      const chinese = messages.zh[key as keyof typeof messages.zh];
      if (!intentionallyEmpty.has(key))
        expect(english.trim(), key).not.toBe("");
      expect(chinese.trim(), key).not.toBe("");
      expect(placeholders(chinese), key).toEqual(placeholders(english));
      if (english === chinese) {
        expect(ALLOWED_IDENTICAL_TERMS).toContain(english);
      }
    }
  });

  it("renders stable API error codes in the current locale", () => {
    expect(localizeError({ code: "stale_revision" }, "zh")).toContain(
      "草稿已在其他地方更新",
    );
    expect(statusLabel("generating", "zh")).toBe("生成中");
  });

  it("uses the exact civic observer template label in both locales", () => {
    expect(avatarTemplateLabel("maya-civic-observer", "fallback", "en")).toBe(
      "Maya Civic Observer",
    );
    expect(avatarTemplateLabel("maya-civic-observer", "fallback", "zh")).toBe(
      "Maya 公民观察员",
    );
  });
});
