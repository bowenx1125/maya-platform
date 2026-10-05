"use client";

import type { ReactNode } from "react";

import { isConflict } from "../lib/api";
import { localizeError, statusLabel } from "../lib/i18n";
import type { UiGuideKey } from "../lib/ui-guide-copy";
import { useLocale, useT } from "./locale";

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

export function ErrorNotice({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const t = useT();
  const { locale } = useLocale();
  const conflict = isConflict(error);
  return (
    <div
      className={conflict ? "notice notice-warning" : "notice notice-error"}
      role="alert"
    >
      <strong>{conflict ? t("revisionConflict") : t("requestFailed")}</strong>
      <span>
        {conflict ? t("retryConflict") : localizeError(error, locale)}
      </span>
      {onRetry ? (
        <button className="inline-button" type="button" onClick={onRetry}>
          {t("retry")}
        </button>
      ) : null}
    </div>
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
}: {
  title?: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  guide?: UiGuideKey;
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
              <h2 data-ui-guide={guide} tabIndex={guide ? 0 : undefined}>
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
