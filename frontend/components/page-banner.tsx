"use client";

import type { ReactNode } from "react";

import { cn } from "../lib/utils";
import { AGENT_BANNER, AGENT_BANNER_TITLE } from "./agent-chrome";

/**
 * Shared page header shell (Chatform / Agents / Teams): sunburst banner with
 * the title on the left and page actions (Back / Done / New) on the right.
 */
export function PageBanner({
  title,
  titleId,
  children,
  className,
  titleClassName,
}: {
  title: ReactNode;
  titleId?: string;
  /** Right-side actions (PageAction Back / Done / New). */
  children?: ReactNode;
  className?: string;
  titleClassName?: string;
}) {
  return (
    <header className={cn(AGENT_BANNER, "mb-5 justify-between", className)}>
      <h1
        id={titleId}
        className={cn(AGENT_BANNER_TITLE, "flex-none", titleClassName)}
      >
        {title}
      </h1>
      {children ? (
        <div className="ml-auto flex shrink-0 items-center gap-3">
          {children}
        </div>
      ) : null}
    </header>
  );
}
