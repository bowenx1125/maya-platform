"use client";

import type { ReactNode } from "react";

import {
  AGENT_PAGE,
  STUDYFORM_BANNER,
  STUDYFORM_BANNER_TITLE,
} from "./agent-chrome";

/**
 * The Agents page (r2-list.mjs list A / empty E2): the sunburst banner with
 * the title and, when there are Agents, "+ New"; one white panel below holds
 * the card A grid or the E2 spotlight.
 */
export function AgentsPage({
  title,
  action,
  children,
}: {
  title: string;
  /** Header "+ New" (none in the empty state; it sits in the card). */
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={AGENT_PAGE}>
      <header className={STUDYFORM_BANNER}>
        <h1
          id="studyform-agents"
          className={STUDYFORM_BANNER_TITLE}
        >
          {title}
        </h1>
        {action}
      </header>
      <section
        aria-labelledby="studyform-agents"
        className="rounded-[16px] border-[3px] border-[#111] bg-white px-7 pt-[35px] pb-[34px] shadow-[8px_8px_0_#111] max-[767px]:px-4 max-[767px]:py-6"
      >
        {children}
      </section>
    </div>
  );
}
