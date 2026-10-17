"use client";

import { useState, type HTMLAttributes, type ReactNode } from "react";

import { useT } from "./locale";
import { IconClose } from "./quiet-icons";

/**
 * The compact × that closes an error, failure or warning line. Closing only
 * hides the line on this screen; it never changes anything on the server.
 */
export function DismissButton({
  onDismiss,
  label,
}: {
  onDismiss: () => void;
  label?: string;
}) {
  const t = useT();
  return (
    <button
      type="button"
      className="alert-dismiss"
      aria-label={label ?? t("noticeDismiss")}
      title={label ?? t("noticeDismiss")}
      onClick={onDismiss}
    >
      <IconClose size={12} />
    </button>
  );
}

const NOT_DISMISSED = Symbol("not-dismissed");
const SAME_MOUNT = Symbol("same-mount");

/**
 * An error, failure or warning line that its reader can close with ×.
 *
 * It stays closed until `resetKey` changes (a new error object or message),
 * or until the line is unmounted and shown again, so a later failure is never
 * swallowed by an earlier dismissal. Plain-text children are their own key.
 */
export function DismissibleAlert({
  as: Tag = "p",
  className,
  role = "alert",
  resetKey,
  dismissLabel,
  children,
  ...rest
}: {
  as?: "p" | "div" | "span";
  className?: string;
  role?: "alert" | "status";
  resetKey?: unknown;
  dismissLabel?: string;
  children: ReactNode;
} & Omit<HTMLAttributes<HTMLElement>, "children" | "role" | "className">) {
  const [dismissed, setDismissed] = useState<unknown>(NOT_DISMISSED);
  const key =
    resetKey !== undefined
      ? resetKey
      : typeof children === "string" || typeof children === "number"
        ? children
        : SAME_MOUNT;
  if (dismissed !== NOT_DISMISSED && Object.is(dismissed, key)) return null;
  return (
    <Tag
      {...rest}
      className={
        className ? `dismissible-alert ${className}` : "dismissible-alert"
      }
      role={role}
    >
      <span className="dismissible-alert-body">{children}</span>
      <DismissButton label={dismissLabel} onDismiss={() => setDismissed(key)} />
    </Tag>
  );
}
