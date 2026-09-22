import type { ReactNode } from "react";

import { WorkspaceAppearance } from "../../components/workspace-appearance";

export default function TeacherLayout({ children }: { children: ReactNode }) {
  return <WorkspaceAppearance>{children}</WorkspaceAppearance>;
}
