import type { Metadata } from "next";
import { Bricolage_Grotesque, Lexend } from "next/font/google";
import type { ReactNode } from "react";

import { SessionProvider } from "../components/session-provider";
import { UiGuideTooltip } from "../components/ui-guide-tooltip";

import "./app.css";

// Arcade type (DESIGN-RULES §2). Only the CSS variables are set on <html>, so
// legacy pages keep their own faces until they move to Arcade.
const display = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: "800",
  variable: "--font-bricolage",
  display: "swap",
});
const body = Lexend({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-lexend",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Mayaform",
  description:
    "A local-first classroom platform for evidence-aware cultural debate.",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en-US" className={`${display.variable} ${body.variable}`}>
      <body>
        <SessionProvider>
          {children}
          <UiGuideTooltip />
        </SessionProvider>
      </body>
    </html>
  );
}
