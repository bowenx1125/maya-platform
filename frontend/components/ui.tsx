"use client";

import type { ReactNode } from "react";

import { apiErrorMessage, isConflict } from "../lib/api";
import { statusLabel, t } from "../lib/i18n";

export function LoadingCard({ label = t("loading") }: { label?: string }) {
  return (
    <div className="loading-card" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
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
  const conflict = isConflict(error);
  return (
    <div
      className={conflict ? "notice notice-warning" : "notice notice-error"}
      role="alert"
    >
      <strong>{conflict ? t("revisionConflict") : t("requestFailed")}</strong>
      <span>{conflict ? t("retryConflict") : apiErrorMessage(error)}</span>
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
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="empty-card">
      <span className="empty-mark" aria-hidden="true">
        ✦
      </span>
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
      {statusLabel(status)}
    </span>
  );
}

export function PageIntro({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-intro">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {action ? <div className="page-intro-action">{action}</div> : null}
    </div>
  );
}

export function SectionCard({
  title,
  description,
  action,
  children,
  className = "",
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`section-card ${className}`}>
      <div className="section-card-header">
        <div>
          <h2>{title}</h2>
          {description ? <p>{description}</p> : null}
        </div>
        {action ? <div>{action}</div> : null}
      </div>
      {children}
    </section>
  );
}
