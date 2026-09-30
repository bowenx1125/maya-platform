"use client";

import Link from "next/link";
import type { MouseEventHandler } from "react";

import styles from "./page-action.module.css";
import { WorkspaceIcon } from "./workspace-icon";

const labels = { new: "New", back: "Back", done: "Done" } as const;

/**
 * New, Back and Done render where the page puts them, beside the content they
 * act on; the sidebar only lists places to go.
 */
export function PageAction({
  name,
  href,
  form,
  onClick,
  disabled,
}: {
  name: keyof typeof labels;
  href?: string;
  form?: string;
  onClick?: MouseEventHandler<HTMLAnchorElement | HTMLButtonElement>;
  disabled?: boolean;
}) {
  const className = `${name === "done" ? "primary-action" : "text-link"} ${styles.action}`;
  const content = (
    <>
      <WorkspaceIcon name={name} />
      <span>{labels[name]}</span>
    </>
  );
  // A link cannot be disabled, so a routed action that cannot run yet is a
  // disabled button instead of a link that still navigates on Enter.
  return href && !disabled ? (
    <Link className={className} href={href} onClick={onClick}>
      {content}
    </Link>
  ) : (
    <button
      className={className}
      type={form ? "submit" : "button"}
      form={form}
      disabled={disabled}
      onClick={onClick}
    >
      {content}
    </button>
  );
}
