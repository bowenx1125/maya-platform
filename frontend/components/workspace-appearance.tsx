import type { ReactNode } from "react";

import styles from "./workspace-appearance.module.css";

/** Keep product tokens below the route boundary so sign-in stays unchanged. */
export function WorkspaceAppearance({ children }: { children: ReactNode }) {
  return <div className={styles.appearance}>{children}</div>;
}
