import type { ReactNode } from "react";

import { SectionCard } from "./ui";

export function StudyformModule({
  title,
  count,
  action,
  children,
}: {
  title: string;
  count?: number;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <SectionCard
      title={count === undefined ? title : `${title} · ${count}`}
      action={action}
    >
      {children}
    </SectionCard>
  );
}
