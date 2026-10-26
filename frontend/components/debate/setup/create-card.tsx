import type { ReactNode } from "react";
import type { UiGuideKey } from "../../../lib/ui-guide-copy";
import { cn } from "../../../lib/utils";
import { CREATE_CARD, CREATE_CARD_TITLE } from "../debate-chrome";

/**
 * A create-page card (F `.create .card`). Same heading semantics as the
 * shared SectionCard — an h2 that carries the ui-guide hook — with the
 * Debates chrome. `action` sits at the right of the title row.
 */
export function CreateCard({
  title,
  action,
  children,
  className,
  guide,
  headingLevel = 2,
  id,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  guide?: UiGuideKey;
  headingLevel?: 2 | 3;
  id?: string;
}) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const heading = (
    <Heading
      className={cn(CREATE_CARD_TITLE, action && "flex-1")}
      data-ui-guide={guide}
      tabIndex={guide ? 0 : undefined}
    >
      {title}
    </Heading>
  );
  return (
    <section id={id} className={cn(CREATE_CARD, className)}>
      {action ? (
        <div className="flex items-center gap-2.5">
          {heading}
          {action}
        </div>
      ) : (
        heading
      )}
      {children}
    </section>
  );
}
