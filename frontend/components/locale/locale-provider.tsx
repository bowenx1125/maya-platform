"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  createTranslator,
  localeToHtmlLang,
  LOCALE_COOKIE,
  normalizeLocale,
  type Locale,
  type MessageKey,
  type MessageValues,
  type Translator,
} from "../../lib/i18n";

export type LocaleContextValue = {
  locale: Locale;
  htmlLang: "en-US" | "zh-CN";
  setLocale: (locale: Locale) => void;
  toggleLocale: () => void;
  t: Translator;
};

function persistLocale(locale: Locale): void {
  if (typeof document === "undefined") return;
  // This is deliberately a presentation-only cookie: no identity, session,
  // or business state is persisted here.
  document.cookie = `${LOCALE_COOKIE}=${locale}; Path=/; SameSite=Lax`;
  document.documentElement.lang = localeToHtmlLang(locale);
}

const defaultLocale: Locale = "en";
const defaultContext: LocaleContextValue = {
  locale: defaultLocale,
  htmlLang: localeToHtmlLang(defaultLocale),
  setLocale: () => undefined,
  toggleLocale: () => undefined,
  t: createTranslator(defaultLocale),
};

const LocaleContext = createContext<LocaleContextValue>(defaultContext);

export function LocaleProvider({
  children,
  initialLocale = "en",
}: {
  children: ReactNode;
  initialLocale?: Locale | string | null;
}) {
  const [locale, setLocaleState] = useState<Locale>(() =>
    normalizeLocale(initialLocale),
  );

  const setLocale = useCallback((nextLocale: Locale) => {
    const normalized = normalizeLocale(nextLocale);
    // Update the visible document and preference in the same event as the
    // state transition. This avoids a frame with the old lang/cookie value.
    persistLocale(normalized);
    setLocaleState(normalized);
  }, []);

  const toggleLocale = useCallback(() => {
    setLocale(locale === "en" ? "zh" : "en");
  }, [locale, setLocale]);

  useEffect(() => {
    // The initial server-rendered lang is already correct; this keeps the DOM
    // in sync after hydration and covers a browser test mounting the provider
    // without the Next root layout.
    persistLocale(locale);
  }, [locale]);

  const value = useMemo<LocaleContextValue>(
    () => ({
      locale,
      htmlLang: localeToHtmlLang(locale),
      setLocale,
      toggleLocale,
      t: createTranslator(locale),
    }),
    [locale, setLocale, toggleLocale],
  );

  return (
    <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
  );
}

export function useLocale(): LocaleContextValue {
  return useContext(LocaleContext);
}

/** Shared translation hook for every current and future Wave component. */
export function useT(): Translator {
  return useLocale().t;
}

/** A server-safe helper for code that receives a key and explicit locale. */
export function translate(
  locale: Locale,
  key: MessageKey,
  values?: MessageValues,
): string {
  const translator = createTranslator(locale);
  return values ? translator(key, values) : translator(key);
}
