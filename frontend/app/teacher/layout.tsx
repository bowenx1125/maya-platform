"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

import { AppShell } from "../../components/app-shell";
import { RouteGuard } from "../../components/session-provider";
import { WorkspaceAppearance } from "../../components/workspace-appearance";

export default function TeacherLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  // The immersive stage has its own full-screen controls, without a sidebar.
  const stage = pathname.startsWith("/teacher/debates-beta/");
  return (
    <WorkspaceAppearance>
      {stage ? (
        children
      ) : (
        <RouteGuard role="teacher">
          <AppShell role="teacher">{children}</AppShell>
        </RouteGuard>
      )}
    </WorkspaceAppearance>
  );
}
