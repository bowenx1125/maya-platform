import type { ReactNode } from "react";
import Link from "next/link";
import { useT } from "../lib/i18n";
import { cn } from "../lib/utils";
import { IconPlus } from "./quiet-icons";
import { buttonVariants } from "./ui/button";
import {
  AGENT_GRID_CLASS,
  AgentCard,
  agentMascot,
  type AgentRename,
} from "./ui/agent-card";

import styles from "./knowledge/brainform-workspace.module.css";
import { WorkspaceIcon } from "./workspace-icon";

export function ModuleGrid({
  children,
  variant,
  paneOpen = false,
}: {
  children: ReactNode;
  /** A RAG or Record page is open: only it shows, as on Brainform. */
  paneOpen?: boolean;
  /** "studyform": the 2-top / 3-bottom Studyform layout. */
  /** "teacherStudyform": Agents / Teams / Record over RAG / Knowledge /
      Voices, three columns a row. */
  variant?: "studyform" | "teacherStudyform";
}) {
  return (
    <div
      className={
        variant === "studyform"
          ? styles.studyformGrid
          : variant === "teacherStudyform"
            ? `${styles.studyformGrid} ${styles.teacherStudyformGrid}`
            : styles.sections
      }
      data-pane-open={paneOpen || undefined}
    >
      {children}
    </div>
  );
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

export function ModuleTiles({
  children,
  variant,
}: {
  children: ReactNode;
  /** "list": the Agents page grid of 186px card A columns. */
  variant?: "list";
}) {
  return (
    <ul
      className={
        variant === "list"
          ? "m-0 grid list-none items-center grid-cols-[repeat(auto-fill,186px)] gap-x-[26px] gap-y-[30px] p-0 max-[767px]:grid-cols-2"
          : AGENT_GRID_CLASS
      }
    >
      {children}
    </ul>
  );
}

/**
 * The nth version reads 1.0 + (n - 1) × 0.1 with one decimal: 1st V1.0,
 * 6th V1.5, 11th V2.0, 12th V2.1. Integer math keeps it exact. The server
 * builds Agent labels the same way (app/core/version_label.py).
 */
export function versionLabel(ordinal: number) {
  const index = Math.max(0, Math.trunc(ordinal) - 1);
  return `V${1 + Math.floor(index / 10)}.${index % 10}`;
}

/** Teams count version_seq from 1 (Agents from 0), so seq 1 is the 1st. */
export function teamVersionLabel(seq: number) {
  return versionLabel(seq);
}

export function VersionTile({
  id,
  name,
  href,
  label,
  pending,
  visibility,
  deleting = false,
  onDelete,
  deleteLabel,
  title,
  editedBy,
  materialTheme,
  rename,
  variant,
}: {
  /** "list": card A of the Agents page. */
  variant?: "list";
  /** Picks the mascot when there is no avatar theme (defaults to href). */
  id?: string;
  name: string;
  href: string;
  /** ui-guide hover help: the last editor. */
  title?: string;
  /** Last editor's name for the card footer. */
  editedBy?: string | null;
  /** avatar_config.material_theme of the current version. */
  materialTheme?: string | null;
  label: string;
  pending: boolean;
  visibility?: "private" | "public";
  deleting?: boolean;
  onDelete?: () => void;
  deleteLabel: string;
  rename?: AgentRename;
}) {
  const t = useT();
  return (
    <AgentCard
      id={id ?? href}
      name={name}
      href={href}
      label={label}
      pending={pending}
      visibility={visibility}
      visibilityLabel={
        visibility === "public"
          ? t("publicOption")
          : visibility === "private"
            ? t("privateOption")
            : undefined
      }
      mascot={agentMascot(id ?? href, materialTheme)}
      footer={editedBy ? t("agentLastEditedBy", { name: editedBy }) : null}
      guideText={title}
      deleting={deleting}
      onDelete={onDelete}
      deleteLabel={deleteLabel}
      rename={rename}
      variant={variant}
    />
  );
}

/** The same + as ModulePlus, opening a file picker instead of a page. */
export function ModuleUpload({
  label,
  caption,
  accept,
  disabled,
  onFile,
  className,
}: {
  /** Replaces the default button look (the Agent card's "+ New"). */
  className?: string;
  label: string;
  /** Visible text next to the +. Defaults to label; Brainform passes "New". */
  caption?: string;
  accept: string;
  disabled?: boolean;
  onFile: (file: File) => void;
}) {
  return (
    <label
      className={cn(
        className ??
          cn(
            buttonVariants({ variant: "default" }),
            "m-0 gap-1.5 font-display text-base font-extrabold",
          ),
        disabled && "pointer-events-none opacity-50",
      )}
      aria-disabled={disabled || undefined}
      data-ui-guide="agent.uploadRag"
    >
      <IconPlus size={16} />
      <span aria-hidden="true">{caption ?? label}</span>
      <input
        className="sr-only"
        type="file"
        accept={accept}
        aria-label={label}
        disabled={disabled}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFile(file);
          event.currentTarget.value = "";
        }}
      />
    </label>
  );
}

export function ModulePlus({
  href,
  label,
  disabled,
  busy,
  onClick,
}: {
  href?: string;
  label: string;
  disabled?: boolean;
  /** Work this + started is still running: it shows a spinner. */
  busy?: boolean;
  onClick?: () => void;
}) {
  const icon = busy ? (
    <span className="spinner" aria-hidden="true" />
  ) : (
    <WorkspaceIcon name="new" />
  );
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
      aria-busy={busy || undefined}
      disabled={disabled || busy}
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
