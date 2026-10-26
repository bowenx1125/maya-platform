"use client";

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
const BANNER_ACTION =
  "inline-flex h-auto w-auto shrink-0 cursor-pointer items-center gap-1.5 rounded-[10px] border-[3px] border-[#111] px-4 py-[7px] font-body text-sm leading-[1.5] font-extrabold text-[#111] no-underline shadow-[0_5px_0_#111] disabled:cursor-not-allowed disabled:opacity-50 [&_svg]:size-4";

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
  placement,
  className,
}: {
  name: WorkspaceActionName;
  href?: string;
  form?: string;
  onClick?: MouseEventHandler<HTMLAnchorElement | HTMLButtonElement>;
  disabled?: boolean;
  placement?: "page";
  className?: string;
}) {
  const registration = (
    <WorkspaceAction
      name={name}
      href={href}
      form={form}
      onClick={onClick}
      disabled={disabled}
      placement={placement}
    />
  );
  if (placement !== "page") return registration;
  const label = LABELS[name];
  const classes = cn(
    BANNER_ACTION,
    name === "done" ? "bg-[#FF4D8D]" : "bg-white",
    className,
  );
  const content = (
    <>
      <WorkspaceIcon name={name} size={16} />
      <span>{label}</span>
    </>
  );
  return (
    <>
      {registration}
      {href && !disabled ? (
        <Link
          className={classes}
          href={href}
          onClick={onClick}
          data-ui-guide={`workspace.${name}`}
        >
          {content}
        </Link>
      ) : (
        <button
          className={classes}
          type={form ? "submit" : "button"}
          form={form}
          disabled={disabled}
          onClick={onClick}
          data-ui-guide={`workspace.${name}`}
        >
          {content}
        </button>
      )}
    </>
  );
}
