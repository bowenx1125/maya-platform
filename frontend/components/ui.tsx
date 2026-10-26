"use client";

import Link from "next/link";
import {
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { isConflict } from "../lib/api";
import { localizeError, statusLabel, type MessageKey } from "../lib/i18n";
import type { UiGuideKey } from "../lib/ui-guide-copy";
import { useT } from "../lib/i18n";
import { cn } from "../lib/utils";
import { IconClose, IconEdit } from "./quiet-icons";
import { buttonVariants } from "./ui/button";
import { NOTICE_TAIL_CLASS, noticeTray, useNoticeTray } from "./notice-tray";
import {
  KindSticker,
  MascotBadge,
  RetryPill,
  RoundX,
  useTransientFold,
  type ErrorKind,
} from "./ui/error-kit";

export { KindSticker, RetryPill, RoundX, type ErrorKind };

export { NOTICE_TAIL_CLASS, useNoticeTray };

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

/**
 * Lift the tray above a Chat composer while it is on screen (option C: in
 * Chat the mascot speaks from just above the message box).
 */
export function useNoticeTrayAbove(target: HTMLElement | null) {
  useEffect(() => {
    if (!target) return;
    const root = document.documentElement;
    let frame = 0;
    const place = () => {
      frame = 0;
      // Fixed boxes sit in the layout viewport; the visual viewport is what
      // is really on screen (a phone keyboard or pinch zoom shrinks it).
      const layoutHeight = window.innerHeight;
      const view = window.visualViewport;
      const viewTop = view ? view.offsetTop : 0;
      const viewBottom = view ? view.offsetTop + view.height : layoutHeight;
      const top = target.getBoundingClientRect().top;
      const edge = Math.min(Math.max(top, viewTop), viewBottom);
      root.style.setProperty(
        "--arc-tray-bottom",
        `${Math.max(12, layoutHeight - edge + 12)}px`,
      );
      root.style.setProperty(
        "--arc-tray-max",
        `${Math.max(0, edge - viewTop - 24)}px`,
      );
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(place);
    };
    place();
    const observer =
      typeof ResizeObserver === "function"
        ? new ResizeObserver(schedule)
        : null;
    observer?.observe(target);
    observer?.observe(document.body);
    const view = window.visualViewport;
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, {
      capture: true,
      passive: true,
    });
    view?.addEventListener("resize", schedule);
    view?.addEventListener("scroll", schedule);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, { capture: true });
      view?.removeEventListener("resize", schedule);
      view?.removeEventListener("scroll", schedule);
      root.style.removeProperty("--arc-tray-bottom");
      root.style.removeProperty("--arc-tray-max");
    };
  }, [target]);
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
  badge,
  kind,
  transient = false,
}: {
  id?: string;
  /** A field error: the sticker number its field wears, instead of the dot. */
  badge?: number;
  /** U3: the sticker shape that tells the error's kind (default: server). */
  kind?: ErrorKind;
  /** Chat and live classroom errors fold into the mascot badge after 6 s. */
  transient?: boolean;
  tone: "error" | "warning" | "success" | "info";
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  inline?: boolean;
  onClose?: () => void;
}) {
  const t = useT();
  const [closed, setClosed] = useState(false);
  // All feedback is spoken by the mascot: errors and warnings always float
  // in the tray; only success/info lines may stay inline.
  inline = inline && (tone === "success" || tone === "info");
  const tray = useNoticeTray(!inline);
  const fold = useTransientFold(transient && !inline, children);
  if (closed || (!inline && !tray)) return null;
  const sticker: ErrorKind | undefined =
    badge !== undefined
      ? "field"
      : tone === "error"
        ? (kind ?? "server")
        : undefined;
  const notice = (
    <div
      id={id}
      className={cn(
        `notice notice-${tone}`,
        "relative my-4 flex w-full items-start gap-2.5 rounded-[18px] border-[3px] border-border bg-surface py-3 pr-[42px] pl-3.5 text-left font-body text-sm leading-[1.45] font-medium text-ink shadow-[4px_4px_0_#111] max-[680px]:flex-wrap",
        // Status dot instead of an icon font; the colour carries the tone.
        sticker
          ? "items-center pr-[46px] pl-4"
          : "before:mt-1 before:size-3.5 before:flex-none before:rotate-[-8deg] before:rounded-full before:border-2 before:border-border before:bg-main before:shadow-[2px_2px_0_#111] before:content-['']",
        NOTICE_TONE[tone],
        fold.folded && "hidden",
        !inline && cn("pointer-events-auto my-0 flex-none", NOTICE_TAIL_CLASS),
      )}
      role={tone === "error" || tone === "warning" ? "alert" : "status"}
    >
      {sticker ? <KindSticker kind={sticker} n={badge} /> : null}
      {title ? <strong className="whitespace-nowrap">{title}</strong> : null}
      {children ? <span className="min-w-0 flex-1">{children}</span> : null}
      {action}
      <RoundX
        className="notice-close absolute top-[9px] right-[10px]"
        aria-label={t("noticeDismiss")}
        onClick={() => (onClose ? onClose() : setClosed(true))}
      />
    </div>
  );
  if (inline || !tray) return notice;
  return (
    <>
      {createPortal(notice, tray)}
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

/** Sticker (14 option A): a tilted round red number; green with ✓ once fixed. */
export const STICKER =
  "flex-none rotate-[-8deg] rounded-full border-2 border-border text-center font-body font-extrabold shadow-[2px_2px_0_#111]";
export const STICKER_TONE = (done: boolean) =>
  done
    ? "grid place-items-center bg-[#22C55E] text-ink"
    : "bg-[#EF4444] text-white";

/** The number sticker on an offending field (shared by every form error). */
export function StickerBadge({
  n,
  done = false,
}: {
  n: number;
  done?: boolean;
}) {
  return (
    <span
      aria-hidden="true"
      data-checklist-badge
      data-done={done || undefined}
      className={cn(
        STICKER,
        "absolute -top-[13px] -left-[13px] z-[5] size-7 text-[13px] leading-6",
        STICKER_TONE(done),
      )}
    >
      {done ? "✓" : n}
    </span>
  );
}

const NOTICE_TONE = {
  error: "bg-err-bg before:bg-err",
  warning: "bg-warn-bg before:bg-warn",
  success: "bg-ok-bg before:bg-ok",
  info: "",
} as const;

/** A notice's own action (Retry, Refresh): a small neutral button. */
export const NOTICE_ACTION_CLASS = cn(
  "inline-button ml-auto",
  buttonVariants({ variant: "neutral", size: "sm" }),
  "h-8 px-3 text-[13px]",
);

/** U3: an upload or filename refusal wears the file sticker. */
function isFileError(error: unknown) {
  if (!error || typeof error !== "object") return false;
  const { code } = error as { code?: unknown };
  return typeof code === "string" && /file|upload|attachment/.test(code);
}

/** A missing record, as opposed to one the server named a reason for. */
export function isNotFound(error: unknown) {
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
  id,
  error,
  onRetry,
  inline = false,
  notFound,
  onClosed,
  kind,
  transient,
  badge,
}: {
  id?: string;
  kind?: ErrorKind;
  /** U3: the number of the field this error describes. */
  badge?: number;
  transient?: boolean;
  /** Runs after the X closes it, e.g. to give focus back to a field. */
  onClosed?: () => void;
  error: unknown;
  onRetry?: () => void;
  inline?: boolean;
  notFound?: MessageKey;
}) {
  const t = useT();
  // A new error shows again even where an earlier one was closed.
  const [dismissed, setDismissed] = useState<unknown>(null);
  if (dismissed === error) return null;
  const conflict = isConflict(error);
  const missing = isNotFound(error);
  return (
    <Notice
      id={id}
      tone={conflict ? "warning" : "error"}
      title={conflict ? t("revisionConflict") : undefined}
      inline={inline}
      kind={kind ?? (isFileError(error) ? "file" : "server")}
      badge={badge}
      transient={transient}
      onClose={() => {
        setDismissed(error);
        onClosed?.();
      }}
      action={
        // Retrying with the stale revision would only conflict again: offer
        // a reload, which reads the latest revision from the server.
        conflict ? (
          <RetryPill onClick={() => window.location.reload()}>
            {t("refreshPage")}
          </RetryPill>
        ) : // Asking again for a deleted record cannot succeed.
        onRetry && !missing ? (
          <RetryPill onClick={onRetry}>{t("retry")}</RetryPill>
        ) : null
      }
    >
      {conflict
        ? t("retryConflict")
        : notFound && missing
          ? t(notFound)
          : localizeError(error)}
      <ErrorFixLinks error={error} />
    </Notice>
  );
}

type FixLink = { href: string; label: string };

/**
 * Where to fix what the error names (owner decision 2026-10-24): the Agent a
 * Team or Debate refused, or the reader's own Teams that still hold an Agent.
 */
function ErrorFixLinks({ error }: { error: unknown }) {
  const t = useT();
  if (!error || typeof error !== "object") return null;
  const { code, details } = error as { code?: unknown; details?: unknown };
  if (!details || typeof details !== "object") return null;
  const values = details as Record<string, unknown>;
  const student =
    typeof window !== "undefined" &&
    window.location.pathname.startsWith("/student");
  const links: FixLink[] = [];
  if (typeof values.agent_id === "string") {
    const name = typeof values.agent_name === "string" ? values.agent_name : "";
    links.push({
      href: `/${student ? "student" : "teacher"}/agents/${encodeURIComponent(values.agent_id)}`,
      label: t("agentIssueEdit", { name }),
    });
  }
  if (code === "agent_in_team" && Array.isArray(values.teams)) {
    for (const team of values.teams) {
      if (!team || typeof team !== "object") continue;
      const {
        team_id: teamId,
        team_name: teamName,
        group_id: groupId,
      } = team as Record<string, unknown>;
      if (typeof teamId !== "string" || typeof teamName !== "string") continue;
      const query = `mode=team-edit&team_id=${encodeURIComponent(teamId)}`;
      links.push({
        href:
          student && typeof groupId === "string"
            ? `/student/groups/${encodeURIComponent(groupId)}?${query}`
            : `/teacher/studyform?${query}`,
        label: t("errorEditTeam", { name: teamName }),
      });
    }
  }
  if (!links.length) return null;
  return (
    <span className="error-fix-links">
      {links.map((link) => (
        <Link
          key={link.href}
          className="inline-button"
          href={link.href}
          aria-label={link.label}
          title={link.label}
        >
          <IconEdit />
        </Link>
      ))}
    </span>
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
