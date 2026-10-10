import type { ReactNode } from "react";
import Link from "next/link";

import styles from "./knowledge/brainform-workspace.module.css";
import { IconClose } from "./quiet-icons";
import { WorkspaceIcon } from "./workspace-icon";

export function ModuleGrid({ children }: { children: ReactNode }) {
  return <div className={styles.sections}>{children}</div>;
}

export function ModuleCard({
  title,
  count,
  action,
  empty,
  children,
  labelledBy,
}: {
  title: string;
  count?: number;
  action?: ReactNode;
  empty?: string;
  children?: ReactNode;
  labelledBy?: string;
}) {
  return (
    <section className={styles.section} aria-labelledby={labelledBy}>
      <div className={styles.sectionHeading}>
        <h2 id={labelledBy}>{title}</h2>
        {action ??
          (count !== undefined ? (
            <span className={styles.count}>{count}</span>
          ) : null)}
      </div>
      {children ?? (empty ? <p className={styles.empty}>{empty}</p> : null)}
    </section>
  );
}

export function ModuleList({ children }: { children: ReactNode }) {
  return <ul className={styles.list}>{children}</ul>;
}

export function ModuleTiles({ children }: { children: ReactNode }) {
  return <ul className="agent-tile-grid module-tile-grid">{children}</ul>;
}

export function VersionTile({
  name,
  href,
  label,
  pending,
  deleting = false,
  onDelete,
  deleteLabel,
}: {
  name: string;
  href: string;
  label: string;
  pending: boolean;
  deleting?: boolean;
  onDelete?: () => void;
  deleteLabel: string;
}) {
  return (
    <li className="agent-tile">
      <Link className="agent-tile-name text-link" href={href}>
        {name}
      </Link>
      {onDelete ? (
        <button
          type="button"
          className="agent-pill agent-pill-action"
          data-pending={pending ? "true" : "false"}
          disabled={deleting}
          aria-label={deleteLabel}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onDelete();
          }}
        >
          <span className="agent-pill-label">{label}</span>
          <span className="agent-pill-x" aria-hidden="true">
            <IconClose size={12} />
          </span>
        </button>
      ) : (
        <span className="agent-pill" data-pending={pending ? "true" : "false"}>
          {label}
        </span>
      )}
    </li>
  );
}

export function ModulePlus({
  href,
  label,
  disabled,
  onClick,
}: {
  href?: string;
  label: string;
  disabled?: boolean;
  onClick?: () => void;
}) {
  const icon = <WorkspaceIcon name="new" />;
  if (href && !disabled) {
    return (
      <Link className={styles.addButton} href={href} aria-label={label}>
        {icon}
      </Link>
    );
  }
  return (
    <button
      type="button"
      className={styles.addButton}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
    >
      {icon}
    </button>
  );
}

export function ModuleRow({
  title,
  meta,
  badge,
  action,
  href,
  onClick,
  id,
}: {
  title: string;
  meta?: string;
  badge?: ReactNode;
  action?: ReactNode;
  href?: string;
  onClick?: () => void;
  id?: string;
}) {
  const label = href ? (
    <Link className={styles.titleButton} href={href}>
      {title}
    </Link>
  ) : onClick ? (
    <button type="button" className={styles.titleButton} onClick={onClick}>
      {title}
    </button>
  ) : (
    <span className={styles.staticTitle}>{title}</span>
  );
  return (
    <li className={styles.row} id={id}>
      <div className={styles.rowCopy}>
        {label}
        {meta ? <span className={styles.rowMeta}>{meta}</span> : null}
        {badge}
      </div>
      {action ? <div className={styles.actions}>{action}</div> : null}
    </li>
  );
}
