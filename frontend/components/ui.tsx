"use client";

import { useState, useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { isConflict } from "../lib/api";
import { localizeError, statusLabel, type MessageKey } from "../lib/i18n";
import type { UiGuideKey } from "../lib/ui-guide-copy";
import { useLocale, useT } from "./locale";
import { IconClose } from "./quiet-icons";

export function LoadingCard({ label }: { label?: string }) {
  const t = useT();
  return (
    <div className="loading-card" role="status">
      {/* The sign-in's four scholar blocks, still waiting their turn. */}
      <span className="academy-loader" aria-hidden="true">
        <i />
        <i />
        <i />
        <i />
      </span>
      {label ?? t("loading")}
    </div>
  );
}

const noSubscription = () => () => {};

/** One tray at the bottom of the page, so notices never push a page down. */
function noticeTray(): HTMLElement {
  let element = document.querySelector<HTMLElement>(".notice-tray");
  if (!element) {
    element = document.createElement("div");
    element.className = "notice-tray";
    document.body.append(element);
  }
  return element;
}

/** The tray exists only in the browser; the server renders no notice. */
function useNoticeTray(enabled: boolean) {
  const browser = useSyncExternalStore(
    noSubscription,
    () => true,
    () => false,
  );
  return enabled && browser ? noticeTray() : null;
}

/**
 * Every error and notice can be closed with its X. Inline notices stay where
 * they are written, such as under the latest Chat message; the rest float in
 * the bottom tray.
 */
export function Notice({
  id,
  tone,
  title,
  children,
  action,
  inline = false,
  onClose,
}: {
  id?: string;
  tone: "error" | "warning" | "success" | "info";
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  inline?: boolean;
  onClose?: () => void;
}) {
  const t = useT();
  const [closed, setClosed] = useState(false);
  const tray = useNoticeTray(!inline);
  if (closed || (!inline && !tray)) return null;
  const notice = (
    <div
      id={id}
      className={`notice notice-${tone}`}
      role={tone === "error" || tone === "warning" ? "alert" : "status"}
    >
      {title ? <strong>{title}</strong> : null}
      {children ? <span>{children}</span> : null}
      {action}
      <button
        type="button"
        className="notice-close"
        aria-label={t("noticeDismiss")}
        onClick={() => (onClose ? onClose() : setClosed(true))}
      >
        <IconClose />
      </button>
    </div>
  );
  return inline || !tray ? notice : createPortal(notice, tray);
}

/** A missing record, as opposed to one the server named a reason for. */
function isNotFound(error: unknown) {
  if (!error || typeof error !== "object") return false;
  const { code, status } = error as { code?: unknown; status?: unknown };
  return code === "not_found" || (typeof code !== "string" && status === 404);
}

/**
 * The message alone names the problem; a generic "Request failed" heading
 * told the reader nothing. `notFound` says which record went missing, so a
 * deleted Agent reads as a deleted Agent rather than an unknown resource.
 */
export function ErrorNotice({
  error,
  onRetry,
  inline = false,
  notFound,
}: {
  error: unknown;
  onRetry?: () => void;
  inline?: boolean;
  notFound?: MessageKey;
}) {
  const t = useT();
  const { locale } = useLocale();
  // A new error shows again even where an earlier one was closed.
  const [dismissed, setDismissed] = useState<unknown>(null);
  if (dismissed === error) return null;
  const conflict = isConflict(error);
  const missing = isNotFound(error);
  return (
    <Notice
      tone={conflict ? "warning" : "error"}
      title={conflict ? t("revisionConflict") : undefined}
      inline={inline}
      onClose={() => setDismissed(error)}
      action={
        // Asking again for a deleted record cannot succeed.
        onRetry && !missing ? (
          <button className="inline-button" type="button" onClick={onRetry}>
            {t("retry")}
          </button>
        ) : null
      }
    >
      {conflict
        ? t("retryConflict")
        : notFound && missing
          ? t(notFound)
          : localizeError(error, locale)}
    </Notice>
  );
}

export function EmptyCard({
  title,
  children,
  action,
}: {
  title?: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="empty-card">
      {/* The sign-in rule's gold diamond, not a sparkle. */}
      <span className="empty-mark" aria-hidden="true" />
      <h2>{title}</h2>
      {children ? <p>{children}</p> : null}
      {action}
    </section>
  );
}

export function StatusBadge({
  status,
  tone,
}: {
  status: string;
  tone?: "good" | "warn" | "bad" | "neutral";
}) {
  const { locale } = useLocale();
  const derived =
    tone ??
    (status === "ready" || status === "published" || status === "active"
      ? "good"
      : status === "failed" || status === "archived"
        ? "bad"
        : "warn");
  return (
    <span className={`status-badge status-${derived}`}>
      <span aria-hidden="true" />
      {statusLabel(status, locale)}
    </span>
  );
}

export function PageIntro({ title }: { title: string }) {
  return <h1 className="sr-only">{title}</h1>;
}

export function SectionCard({
  title,
  description,
  action,
  children,
  className = "",
  guide,
  guideText,
}: {
  title?: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  guide?: UiGuideKey;
  guideText?: string;
}) {
  // A section directly beneath the page title does not need to repeat it, so
  // the header collapses entirely when there is nothing of its own to say.
  const header = title || description || action;
  return (
    <section className={`section-card ${className}`}>
      {header ? (
        <div className="section-card-header">
          <div>
            {title ? (
              <h2
                data-ui-guide={guide}
                data-ui-guide-text={guideText}
                tabIndex={guide ? 0 : undefined}
              >
                {title}
              </h2>
            ) : null}
            {description ? <p>{description}</p> : null}
          </div>
          {action ? <div>{action}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}
