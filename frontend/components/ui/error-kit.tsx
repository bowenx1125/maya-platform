"use client";

import {
  useEffect,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { cn } from "../../lib/utils";
import { placeNoticeTray, revealNoticeTray } from "../notice-tray";

/**
 * U3 "Icon by Kind" (proposals/15-unified-errors): one pink bubble for every
 * error; the sticker shape tells the kind. These are the shared pieces.
 */

/** The one shared round × (26px, 2px border, 2px hard shadow). */
export const ROUND_X_CLASS =
  "m-0 inline-grid size-[26px] min-h-0 flex-none cursor-pointer place-items-center rounded-full border-2 border-border bg-surface p-0 text-ink shadow-[2px_2px_0_#111] hover:bg-err hover:text-white focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main disabled:cursor-not-allowed disabled:opacity-50";

export function RoundXIcon({ size = 13 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="3.2"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

/** The shared round ×; callers only place it and name it. */
export function RoundX({
  className,
  iconSize,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { iconSize?: number }) {
  return (
    <button type="button" {...rest} className={cn(ROUND_X_CLASS, className)}>
      <RoundXIcon size={iconSize} />
    </button>
  );
}

export type ErrorKind = "field" | "file" | "chat" | "bell" | "server";

const KIND_ICON: Record<Exclude<ErrorKind, "field" | "server">, ReactNode> = {
  file: <path d="M6 3h8l4 4v14H6z" />,
  chat: <path d="M4 5h16v11H9l-5 4z" />,
  bell: <path d="M6 17V11a6 6 0 0 1 12 0v6l2 2H4zM10 21h4" />,
};

const STICKER_BASE =
  "inline-grid size-[26px] flex-none rotate-[-8deg] place-items-center border-2 border-border text-center font-body font-extrabold shadow-[2px_2px_0_#111]";

/** Sits on the offending element, centred on its top-left corner. */
export const STICKER_ON_CLASS =
  "absolute -top-[13px] -left-[13px] z-[5] size-7";

/**
 * A kind sticker: red number circle (field, green ✓ once fixed), red file,
 * speech or bell square, or a black square with a yellow "!" (server).
 */
export function KindSticker({
  kind,
  n = 1,
  done = false,
  on = false,
  className,
}: {
  kind: ErrorKind;
  n?: number;
  done?: boolean;
  on?: boolean;
  className?: string;
}) {
  const place = on ? STICKER_ON_CLASS : "";
  if (kind === "field")
    return (
      <span
        aria-hidden="true"
        data-sticker="field"
        data-done={done || undefined}
        data-n={done ? "✓" : n}
        className={cn(
          STICKER_BASE,
          // The glyph is CSS content, so the line's text stays its copy.
          "rounded-full text-[12px] leading-none before:content-[attr(data-n)]",
          done ? "bg-[#22C55E] text-ink" : "bg-[#EF4444] text-white",
          place,
          className,
        )}
      />
    );
  if (kind === "server")
    return (
      <span
        aria-hidden="true"
        data-sticker="server"
        className={cn(
          STICKER_BASE,
          "rounded-[7px] bg-[#111] text-[14px] font-black text-[#FFE14D] before:content-['!']",
          place,
          className,
        )}
      />
    );
  return (
    <span
      aria-hidden="true"
      data-sticker={kind}
      className={cn(
        STICKER_BASE,
        "rounded-[7px] bg-[#EF4444] text-white",
        place,
        className,
      )}
    >
      <svg
        viewBox="0 0 24 24"
        width="14"
        height="14"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
      >
        {KIND_ICON[kind]}
      </svg>
    </span>
  );
}

/** The white Retry pill (same shape as the pink "Show me" pill). */
export const RETRY_PILL_CLASS =
  "ml-auto inline-flex flex-none cursor-pointer items-center gap-[5px] self-center rounded-full border-2 border-border bg-white px-[11px] py-1 font-body text-[13px] font-bold whitespace-nowrap text-ink shadow-[3px_3px_0_#111] hover:bg-[#FFE4E4] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main";

export function RetryPill({
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" {...rest} className={cn(RETRY_PILL_CLASS, className)}>
      <svg
        viewBox="0 0 24 24"
        width="14"
        height="14"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        aria-hidden="true"
      >
        <path d="M20 12a8 8 0 1 1-3-6.3M20 4v5h-5" />
      </svg>
      {children}
    </button>
  );
}

/** How long a transient (chat, live classroom) bubble stays open. */
export const TRANSIENT_FOLD_MS = 6000;

/**
 * Transient errors fold after 6 s into the mascot's "!" badge; clicking the
 * badge reopens the bubble. A new `key` (a new error) opens it again.
 */
export function useTransientFold(transient: boolean, key: unknown) {
  const [folded, setFolded] = useState<{ key: unknown } | null>(null);
  const isFolded = transient && folded !== null && Object.is(folded.key, key);
  useEffect(() => {
    if (!transient || isFolded) return;
    const timer = window.setTimeout(
      () => setFolded({ key }),
      TRANSIENT_FOLD_MS,
    );
    return () => window.clearTimeout(timer);
  }, [transient, isFolded, key]);
  return { folded: isFolded, reopen: () => setFolded(null) };
}

/** The red "!" on the mascot (never a count); click reopens the bubble. */
export function MascotBadge({
  tray,
  label,
  onOpen,
}: {
  tray: HTMLElement;
  label: string;
  onOpen: () => void;
}) {
  return createPortal(
    <button
      type="button"
      data-mascot-badge
      aria-label={label}
      title={label}
      onClick={onOpen}
      className="mascot-badge pointer-events-auto absolute right-0 bottom-[52px] z-[2] m-0 grid size-[28px] min-h-0 rotate-[-8deg] cursor-pointer place-items-center rounded-full border-2 border-border bg-[#EF4444] p-0 font-body text-[15px] font-black text-white shadow-[2px_2px_0_#111] [body>.notice-tray>&]:right-3 min-[900px]:[body>.notice-tray>&]:right-0"
    >
      !
    </button>,
    tray,
  );
}

/**
 * Where the shared tray sits in the page flow below 900px: the shell renders
 * this right after its main panel. From 900px the tray is fixed, in <body>.
 */
export function NoticeTraySlot({ className }: { className?: string }) {
  return (
    <div
      data-notice-tray-slot=""
      className={className}
      ref={(slot) => {
        placeNoticeTray();
        return () => {
          // Leaving the page: hand the tray back to <body> before the slot
          // goes, so open notices keep a connected tray.
          const tray = slot?.querySelector<HTMLElement>(".notice-tray");
          if (tray) document.body.append(tray);
          placeNoticeTray();
        };
      }}
    />
  );
}

/**
 * U3: when a new error is shown (a new `key`), make sure the reader sees it.
 * Below 900px the tray is in the page flow and may be off screen; it is
 * scrolled into view once, smoothly unless reduced motion is asked for.
 */
export function useRevealNotice(
  tray: HTMLElement | null,
  key: unknown,
  enabled = true,
) {
  useEffect(() => {
    if (!enabled || !tray) return;
    const frame = requestAnimationFrame(() => revealNoticeTray(tray));
    return () => cancelAnimationFrame(frame);
  }, [tray, key, enabled]);
}
