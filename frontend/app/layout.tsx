import type { Metadata } from "next";
import type { ReactNode } from "react";

import { SessionProvider } from "../components/session-provider";

import "./globals.css";

export const metadata: Metadata = {
  title: "Maya Teaching Platform",
  description:
    "A local-first classroom platform for evidence-aware cultural debate.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
