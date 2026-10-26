"use client";

import { useSyncExternalStore } from "react";

const noSubscription = () => () => {};

/**
 * Classes of the one mascot tray (DESIGN option C): the bubble on the left,
 * the gold scholar on the right, the newest bubble's tail pointing at him.
 * Below 900px the tray sits in the page flow under the main panel, so it
 * never covers the page (it is moved into the shell's tray slot); from 900px
 * it is fixed bottom-right, 380px wide. U3: a newer bubble replaces the older
 * ones at every width, and there is no "+N" chip. The mascot is a
 * pseudo-element, so the tray's children stay the notices (and the mascot
 * badge) and `:empty` hides it.
 */
const TRAY_CLASS = [
  "notice-tray relative mt-3.5 flex flex-row items-end justify-end gap-1.5 w-full pointer-events-none font-body empty:hidden",
  "max-[899px]:[body>&]:px-3 max-[899px]:[body>&]:pb-4",
  "min-[900px]:fixed min-[900px]:right-7 min-[900px]:bottom-[var(--arc-tray-bottom,24px)] min-[900px]:z-[60] min-[900px]:m-0 min-[900px]:w-[380px] min-[900px]:p-0",
  "min-[900px]:max-h-[var(--arc-tray-max,calc(100dvh-32px))] min-[900px]:overflow-y-auto min-[900px]:overscroll-contain",
  "after:content-[''] after:block after:flex-none after:w-[58px] after:h-[74px]",
  "after:bg-[url(/mascots/wave.svg)] after:bg-contain after:bg-bottom after:bg-no-repeat after:drop-shadow-[3px_3px_0_#111]",
  "[&>.notice]:flex-1 [&>.notice]:min-w-0 [&>.notice]:max-w-none",
  "[&>.notice:has(~.notice)]:hidden",
].join(" ");

/** Below this width the tray is in the page flow, not fixed. */
export const TRAY_FLOW_QUERY = "(max-width: 899px)";

function inFlow(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia(TRAY_FLOW_QUERY).matches
  );
}

let trayElement: HTMLElement | null = null;
let watching = false;

/** Put the tray where it belongs at this width: the slot in flow, else body. */
export function placeNoticeTray(element: HTMLElement | null = trayElement) {
  if (!element) return;
  const slots = document.querySelectorAll<HTMLElement>(
    "[data-notice-tray-slot]",
  );
  const slot = inFlow() ? slots[slots.length - 1] : undefined;
  const target = slot ?? document.body;
  if (element.parentElement !== target) target.append(element);
}

/** One tray for the page, so notices never stack in several places. */
export function noticeTray(): HTMLElement {
  let element =
    document.querySelector<HTMLElement>(".notice-tray") ?? trayElement;
  if (!element) {
    element = document.createElement("div");
    element.className = TRAY_CLASS;
  }
  trayElement = element;
  placeNoticeTray(element);
  if (!watching && typeof window.matchMedia === "function") {
    watching = true;
    window
      .matchMedia(TRAY_FLOW_QUERY)
      .addEventListener?.("change", () => placeNoticeTray());
  }
  return element;
}

/**
 * Below 900px a newly shown error is in the page flow and may be off screen:
 * bring the tray into view (smoothly, unless the reader asked for reduced
 * motion). From 900px the tray is fixed on screen, so nothing moves.
 */
export function revealNoticeTray(tray: HTMLElement | null) {
  if (!tray || !inFlow()) return;
  const rect = tray.getBoundingClientRect();
  const bottom = window.visualViewport?.height ?? window.innerHeight;
  if (rect.height === 0 || (rect.top >= 0 && rect.bottom <= bottom)) return;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  tray.scrollIntoView?.({
    block: "nearest",
    behavior: reduced ? "auto" : "smooth",
  });
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

/** The tail on the newest tray bubble, pointing right at the mascot. */
export const NOTICE_TAIL_CLASS =
  "[.notice-tray>&:last-child]:after:absolute [.notice-tray>&:last-child]:after:-right-[13px] [.notice-tray>&:last-child]:after:bottom-4 [.notice-tray>&:last-child]:after:size-5 [.notice-tray>&:last-child]:after:rotate-45 [.notice-tray>&:last-child]:after:skew-[10deg] [.notice-tray>&:last-child]:after:border-r-[3px] [.notice-tray>&:last-child]:after:border-t-[3px] [.notice-tray>&:last-child]:after:border-border [.notice-tray>&:last-child]:after:bg-inherit [.notice-tray>&:last-child]:after:content-['']";
