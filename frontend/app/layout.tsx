import type { Metadata } from "next";
import { cookies, headers } from "next/headers";
import type { ReactNode } from "react";

import { LocaleProvider } from "../components/locale";
import { SessionProvider } from "../components/session-provider";
import {
  LOCALE_COOKIE,
  localeToHtmlLang,
  resolveInitialLocale,
} from "../lib/i18n";

import "./globals.css";

export const metadata: Metadata = {
  title: "Mayaform",
  description:
    "A local-first classroom platform for evidence-aware cultural debate.",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  const cookieStore = await cookies();
  const headerStore = await headers();
  const initialLocale = resolveInitialLocale(
    cookieStore.get(LOCALE_COOKIE)?.value,
    headerStore.get("accept-language"),
  );
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
