import type { Metadata } from "next";
import type { ReactNode } from "react";

import { SessionProvider } from "../components/session-provider";
import { UiGuideTooltip } from "../components/ui-guide-tooltip";

import "./globals.css";

export const metadata: Metadata = {
  title: "Mayaform",
  description:
    "A local-first classroom platform for evidence-aware cultural debate.",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en-US">
      <body>
        <SessionProvider>
          {children}
          <UiGuideTooltip />
        </SessionProvider>
      </body>
    </html>
  );
}
