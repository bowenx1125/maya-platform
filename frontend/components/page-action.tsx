"use client";

import type { MouseEventHandler } from "react";

import { WorkspaceAction, type WorkspaceActionName } from "./workspace-actions";

/**
 * Compatibility wrapper for page-owned actions. AppShell renders the single
 * action control in the sidebar while the page keeps ownership of its behavior.
 */
export function PageAction({
  name,
  href,
  form,
  onClick,
  disabled,
}: {
  name: WorkspaceActionName;
  href?: string;
  form?: string;
  onClick?: MouseEventHandler<HTMLAnchorElement | HTMLButtonElement>;
  disabled?: boolean;
}) {
  return (
    <WorkspaceAction
      name={name}
      href={href}
      form={form}
      onClick={onClick}
      disabled={disabled}
    />
  );
}
