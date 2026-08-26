"use client";

import { useLocale } from "./locale-provider";

export function LanguageSwitcher() {
  const { locale, setLocale, t } = useLocale();

  return (
    <div className="locale-switcher" aria-label={t("languageControl")}>
      <span className="locale-label">{t("languageLabel")}</span>
      <div className="locale-options" role="group">
        <button
          className={locale === "zh" ? "locale-option active" : "locale-option"}
          type="button"
          aria-pressed={locale === "zh"}
          aria-label={t("switchToChinese")}
          onClick={() => setLocale("zh")}
        >
          {t("languageChinese")}
        </button>
        <span className="locale-divider" aria-hidden="true">
          /
        </span>
        <button
          className={locale === "en" ? "locale-option active" : "locale-option"}
          type="button"
          aria-pressed={locale === "en"}
          aria-label={t("switchToEnglish")}
          onClick={() => setLocale("en")}
        >
          {t("languageEnglish")}
        </button>
      </div>
    </div>
  );
}
