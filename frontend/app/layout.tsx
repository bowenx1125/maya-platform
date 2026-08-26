import type { Metadata } from "next";
import { cookies } from "next/headers";
import type { ReactNode } from "react";

import { LocaleProvider } from "../components/locale";
import { SessionProvider } from "../components/session-provider";
import { localeToHtmlLang, LOCALE_COOKIE, normalizeLocale } from "../lib/i18n";

import "./globals.css";

export const metadata: Metadata = {
  title: "Maya Teaching Platform",
  description:
    "A local-first classroom platform for evidence-aware cultural debate.",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  const cookieStore = await cookies();
  const initialLocale = normalizeLocale(cookieStore.get(LOCALE_COOKIE)?.value);
  return (
    <html lang={localeToHtmlLang(initialLocale)}>
      <body>
        <SessionProvider>
          <LocaleProvider initialLocale={initialLocale}>
            {children}
          </LocaleProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
