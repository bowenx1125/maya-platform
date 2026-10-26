"use client";

import { useSyncExternalStore } from "react";

const noSubscription = () => () => {};

/**
 * Classes of the one mascot tray (DESIGN option C): fixed bottom-right at
 * z-index 60, the gold scholar speaking from the corner, a tail on the newest
 * bubble only. U3: a newer bubble replaces the older ones at every width,
 * and there is no "+N" chip. The mascot is a pseudo-element, so the tray's
 * children stay the notices (and the mascot badge) and `:empty` hides it.
 */
const TRAY_CLASS = [
  "notice-tray fixed right-6 bottom-[var(--arc-tray-bottom,16px)] z-[60] flex flex-col items-end gap-3",
  "w-[min(440px,calc(100vw-32px))] pointer-events-none font-body empty:hidden",
  "max-h-[var(--arc-tray-max,calc(100dvh-32px))] overflow-y-auto overscroll-contain",
  "after:content-[''] after:block after:flex-none after:mr-3 after:w-24 after:h-[120px]",
  "after:bg-[url(/mascots/wave.svg)] after:bg-contain after:bg-bottom after:bg-no-repeat after:drop-shadow-[3px_3px_0_#111]",
  "max-[680px]:left-3 max-[680px]:right-3 max-[680px]:w-auto max-[680px]:bottom-[var(--arc-tray-bottom,12px)]",
  "max-[680px]:gap-2 max-[680px]:after:w-14 max-[680px]:after:h-[70px] max-[680px]:after:mr-1",
  "max-[680px]:[&>.notice]:text-[13px] max-[680px]:[&>.notice]:py-2.5 max-[680px]:[&>.notice]:pr-[38px] max-[680px]:[&>.notice]:pl-3",
  "[&>.notice:has(~.notice)]:hidden",
].join(" ");

/** One tray at the bottom of the page, so notices never push a page down. */
export function noticeTray(): HTMLElement {
  let element = document.querySelector<HTMLElement>(".notice-tray");
  if (!element) {
    element = document.createElement("div");
    element.className = TRAY_CLASS;
    document.body.append(element);
  }
  return element;
}

/** The tray exists only in the browser; the server renders no notice. */
export function useNoticeTray(enabled: boolean) {
  const browser = useSyncExternalStore(
    noSubscription,
    () => true,
    () => false,
  );
  return enabled && browser ? noticeTray() : null;
}

/** The tail on the newest tray bubble, pointing down at the mascot. */
export const NOTICE_TAIL_CLASS =
  "[.notice-tray>&:last-child]:after:absolute [.notice-tray>&:last-child]:after:right-[30px] [.notice-tray>&:last-child]:after:-bottom-[15px] [.notice-tray>&:last-child]:after:size-[22px] [.notice-tray>&:last-child]:after:rotate-45 [.notice-tray>&:last-child]:after:skew-[10deg] [.notice-tray>&:last-child]:after:border-r-[3px] [.notice-tray>&:last-child]:after:border-b-[3px] [.notice-tray>&:last-child]:after:border-border [.notice-tray>&:last-child]:after:bg-inherit [.notice-tray>&:last-child]:after:content-['']";
