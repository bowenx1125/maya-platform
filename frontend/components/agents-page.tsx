"use client";

import type { ReactNode } from "react";

import { AGENT_PAGE } from "./agent-chrome";
import { PageBanner } from "./page-banner";

/**
 * The Agents page: shared PageBanner (Chatform-sized) with the title and,
 * when there are Agents, New on the right; one panel below holds the card
 * grid or the empty spotlight.
 */
export function AgentsPage({
  title,
  action,
  children,
}: {
  title: string;
  /** Header New (none in the empty state; it sits in the card). */
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={AGENT_PAGE}>
      <PageBanner
        title={title}
        titleId="studyform-agents"
        className="max-[767px]:shadow-[8px_8px_0_#111]"
      >
        {action}
      </PageBanner>
      <section aria-labelledby="studyform-agents">{children}</section>
    </div>
  );
}
