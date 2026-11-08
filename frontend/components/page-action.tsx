"use client";
import { BUSY_MOTION, BUSY_MOTION_PRIMARY, PRESS_MOTION } from "./ui/button";

import Link from "next/link";
import type { MouseEventHandler } from "react";

import { cn } from "../lib/utils";
import { WorkspaceIcon } from "./workspace-icon";
import { WorkspaceAction, type WorkspaceActionName } from "./workspace-actions";

const LABELS: Record<WorkspaceActionName, string> = {
  new: "New",
  back: "Back",
  done: "Done",
};

/** Agent banner button (approved O2 / option A `.ph .pa`). */
export const BANNER_ACTION = `inline-flex h-auto min-h-11 w-auto shrink-0 cursor-pointer items-center gap-1.5 rounded-[10px] border-[3px] border-[#111] px-4 py-[7px] font-body text-sm [line-height:normal] font-extrabold text-[#111] no-underline disabled:cursor-not-allowed disabled:opacity-50 disabled:aria-busy:opacity-100 [&_svg]:size-4 ${PRESS_MOTION}`;

/**
 * The one look for New / Back / Done wherever a page draws them (its
 * banner, or the shell's row above a page without one): New and Done pink,
 * Back white, symbol plus word, the shared press and busy motion.
 */
export function pageActionClass(
  name: WorkspaceActionName,
  className?: string,
): string {
  const primary = name !== "back";
  return cn(
    BANNER_ACTION,
    primary ? "bg-[#FF4D8D]" : "bg-white",
    primary ? BUSY_MOTION_PRIMARY : BUSY_MOTION,
    className,
  );
}

/**
 * Compatibility wrapper for page-owned actions. AppShell renders the single
 * action control in the sidebar while the page keeps ownership of its
 * behavior. With placement="page" the page draws the control in place (the
 * Agent Create/Edit banner) and the sidebar leaves it out.
 */
export function PageAction({
  name,
  href,
  form,
  onClick,
  disabled,
  busy,
  placement,
  className,
  guide,
  describedBy,
}: {
  name: WorkspaceActionName;
  href?: string;
  form?: string;
  onClick?: MouseEventHandler<HTMLAnchorElement | HTMLButtonElement>;
  disabled?: boolean;
  busy?: boolean;
  placement?: "page";
  className?: string;
  /** data-ui-guide override (default workspace.<name>). */
  guide?: string;
  /** aria-describedby for the in-page button. */
  describedBy?: string;
}) {
  const registration = (
    <WorkspaceAction
      name={name}
      href={href}
      form={form}
      onClick={onClick}
      disabled={disabled}
      busy={busy}
      placement={placement}
      guide={guide}
      describedBy={describedBy}
    />
  );
  if (placement !== "page") return registration;
  const label = LABELS[name];
  const classes = pageActionClass(name, className);
  const faded = Boolean(disabled || busy);
  const content = (
    <>
      {busy ? (
        <span className="spinner" aria-hidden="true" />
      ) : (
        <WorkspaceIcon name={name} size={16} />
      )}
      <span>{label}</span>
    </>
  );
  const guideAttr = guide ?? `workspace.${name}`;
  return (
    <>
      {registration}
      {href && !faded ? (
        <Link
          className={classes}
          href={href}
          onClick={onClick}
          aria-describedby={describedBy}
          data-ui-guide={guideAttr}
        >
          {content}
        </Link>
      ) : (
        <button
          className={classes}
          type={form ? "submit" : "button"}
          form={form}
          disabled={faded}
          aria-busy={busy || undefined}
          aria-describedby={describedBy}
          onClick={onClick}
          data-ui-guide={guideAttr}
        >
          {content}
        </button>
      )}
    </>
  );
}
