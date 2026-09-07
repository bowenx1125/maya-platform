import type { Metadata } from "next";
import type { ReactNode } from "react";

import { LocaleProvider } from "../components/locale";
import { SessionProvider } from "../components/session-provider";
import { localeToHtmlLang } from "../lib/i18n";

import "./globals.css";

export const metadata: Metadata = {
  title: "Maya Teaching Platform",
  description:
    "A local-first classroom platform for evidence-aware cultural debate.",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  const initialLocale = "en";
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
