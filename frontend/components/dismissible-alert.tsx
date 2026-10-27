"use client";

import { useRef, useState, type HTMLAttributes, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useT } from "../lib/i18n";
import { NOTICE_TAIL_CLASS, useNoticeTray } from "./notice-tray";
import {
  KindSticker,
  MascotBadge,
  RoundX,
  useRevealNotice,
  useTransientFold,
  type ErrorKind,
} from "./ui/error-kit";

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
    <RoundX
      className="alert-dismiss"
      aria-label={label ?? t("noticeDismiss")}
      title={label ?? t("noticeDismiss")}
      onClick={onDismiss}
    />
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
  kind = "server",
  n,
  done,
  transient = false,
  children,
  ...rest
}: {
  /** U3: the sticker that starts an error line (default: server "!"). */
  kind?: ErrorKind;
  /** The field number, for a field error. */
  n?: number;
  done?: boolean;
  /** Chat and live classroom errors fold into the mascot badge after 6 s. */
  transient?: boolean;
  as?: "p" | "div" | "span";
  className?: string;
  role?: "alert" | "status";
  resetKey?: unknown;
  dismissLabel?: string;
  children: ReactNode;
} & Omit<HTMLAttributes<HTMLElement>, "children" | "role" | "className">) {
  const [dismissed, setDismissed] = useState<unknown>(NOT_DISMISSED);
  // Errors are spoken by the mascot: role=alert lines float in the tray.
  const tray = useNoticeTray(role === "alert");
  const lineRef = useRef<HTMLElement | null>(null);
  // Where the line was written, so Dismiss still finds its form from the tray.
  const anchorRef = useRef<HTMLSpanElement | null>(null);
  const key =
    resetKey !== undefined
      ? resetKey
      : typeof children === "string" || typeof children === "number"
        ? children
        : SAME_MOUNT;
  const t = useT();
  const fold = useTransientFold(transient && tray !== null, key);
  useRevealNotice(tray, key);
  if (dismissed !== NOT_DISMISSED && Object.is(dismissed, key)) return null;
  function dismiss() {
    // Closing removes the focused ×; hand focus to the field this line
    // describes, else the form's submit button, never to <body>.
    const line = lineRef.current;
    const id = line?.id;
    const described = id
      ? Array.from(
          document.querySelectorAll<HTMLElement>("[aria-describedby]"),
        ).find((element) =>
          (element.getAttribute("aria-describedby") ?? "")
            .split(/\s+/)
            .includes(id),
        )
      : undefined;
    const target =
      described ??
      (anchorRef.current ?? line)
        ?.closest("form")
        ?.querySelector<HTMLElement>("[type=submit]") ??
      null;
    target?.focus();
    setDismissed(key);
  }
  const alertLine = (
    <Tag
      {...rest}
      ref={(node: HTMLElement | null) => {
        lineRef.current = node;
      }}
      className={[
        "dismissible-alert",
        className,
        tray
          ? `notice notice-error dismissible-alert-tray pointer-events-auto flex-none ${NOTICE_TAIL_CLASS}`
          : "",
        fold.folded ? "hidden" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      role={role}
    >
      {role === "alert" ? <KindSticker kind={kind} n={n} done={done} /> : null}
      <span className="dismissible-alert-body">{children}</span>
      <DismissButton label={dismissLabel} onDismiss={dismiss} />
    </Tag>
  );
  if (!tray) return alertLine;
  return (
    <>
      <span ref={anchorRef} hidden />
      {createPortal(alertLine, tray)}
      {fold.folded ? (
        <MascotBadge
          tray={tray}
          label={t("noticeReopen")}
          onOpen={fold.reopen}
        />
      ) : null}
    </>
  );
}
