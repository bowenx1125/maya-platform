import type { Metadata } from "next";
import {
  Bricolage_Grotesque,
  Caveat,
  Lexend,
  Space_Mono,
} from "next/font/google";
import type { ReactNode } from "react";

import { PageTransition } from "../components/page-transition";
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
// Album sticker numbers (#01) for RAG and Voices.
const mono = Space_Mono({
  subsets: ["latin"],
  weight: "700",
  variable: "--font-space-mono",
  display: "swap",
});
// Handwriting for the Voices album "Made by" signature line.
const hand = Caveat({
  subsets: ["latin"],
  weight: "700",
  variable: "--font-caveat",
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
    <html
      lang="en-US"
      className={`${display.variable} ${body.variable} ${hand.variable} ${mono.variable}`}
    >
      <head>
        {/* Every page waits on the session before it can ask for data. Asking
          here starts that request with the HTML instead of after the scripts
          have downloaded and hydrated; the session provider takes the answer. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              'window.__mayaEarlySession=fetch("/api/v1/auth/me",{credentials:"same-origin",headers:{Accept:"application/json"}}).catch(function(){return null})',
          }}
        />
      </head>
      <body>
        <SessionProvider>
          <PageTransition>{children}</PageTransition>
          <UiGuideTooltip />
        </SessionProvider>
      </body>
    </html>
  );
}
