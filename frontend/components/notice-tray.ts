"use client";

import { useSyncExternalStore } from "react";

const noSubscription = () => () => {};

/**
 * Classes of the one mascot tray (DESIGN option C): fixed bottom-right at
 * z-index 60, the gold scholar speaking from the corner, a tail on the newest
 * bubble only, and on a phone only the newest two bubbles with the rest
 * folded into "+N". The mascot and the fold are pseudo-elements, so the
 * tray's children stay exactly the notices and `:empty` still hides it.
 */
const TRAY_CLASS = [
  "notice-tray fixed right-6 bottom-[var(--arc-tray-bottom,16px)] z-[60] flex flex-col items-end gap-3",
  "w-[min(440px,calc(100vw-32px))] pointer-events-none font-body empty:hidden",
  "max-h-[var(--arc-tray-max,calc(100dvh-32px))] overflow-y-auto overscroll-contain",
  "after:content-[''] after:block after:flex-none after:mr-3 after:w-24 after:h-[120px]",
  "after:bg-[url(/mascots/wave.svg)] after:bg-contain after:bg-bottom after:bg-no-repeat after:drop-shadow-[3px_3px_0_#111]",
  "data-[more]:before:content-['+'_attr(data-more)] data-[more]:before:self-end",
  "data-[more]:before:rounded-full data-[more]:before:border-2 data-[more]:before:border-border",
  "data-[more]:before:bg-surface data-[more]:before:px-2.5 data-[more]:before:py-0.5",
  "data-[more]:before:text-xs data-[more]:before:font-bold data-[more]:before:shadow-[2px_2px_0_#111]",
  "max-[680px]:left-3 max-[680px]:right-3 max-[680px]:w-auto max-[680px]:bottom-[var(--arc-tray-bottom,12px)]",
  "max-[680px]:gap-2 max-[680px]:after:w-14 max-[680px]:after:h-[70px] max-[680px]:after:mr-1",
  "max-[680px]:[&>.notice]:text-[13px] max-[680px]:[&>.notice]:py-2.5 max-[680px]:[&>.notice]:pr-[38px] max-[680px]:[&>.notice]:pl-3",
  "max-[680px]:[&>.notice:nth-last-child(n+3)]:hidden",
].join(" ");

/** Hidden older bubbles on a phone are counted for the "+N" chip. */
function countFolded(element: HTMLElement) {
  const folded = element.children.length - 2;
  const small = window.matchMedia?.("(max-width: 680px)").matches ?? false;
  if (small && folded > 0) element.setAttribute("data-more", String(folded));
  else element.removeAttribute("data-more");
}

/** One tray at the bottom of the page, so notices never push a page down. */
export function noticeTray(): HTMLElement {
  let element = document.querySelector<HTMLElement>(".notice-tray");
  if (!element) {
    element = document.createElement("div");
    element.className = TRAY_CLASS;
    document.body.append(element);
    const tray = element;
    if (typeof MutationObserver === "function")
      new MutationObserver(() => countFolded(tray)).observe(tray, {
        childList: true,
      });
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
