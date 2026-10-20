"use client";

import { useLayoutEffect, useRef } from "react";

/**
 * Shared title auto-fit (owner request 2026-10-20). A title button keeps the
 * size its tile gives it (one to two lines, as Teams/Agents tiles already do);
 * only the font shrinks, in fixed steps, until the whole title fits. Ellipsis
 * (the existing two-line clamp) is the last resort at the smallest step.
 */
export const FIT_TEXT_SCALES = [1, 0.92, 0.85, 0.78, 0.72] as const;

/** Visual width of a title in Latin-character units: CJK/full-width count 2. */
export function titleWidthUnits(text: string): number {
  let units = 0;
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0;
    units +=
      (code >= 0x1100 && code <= 0x115f) ||
      (code >= 0x2e80 && code <= 0xa4cf) ||
      (code >= 0xac00 && code <= 0xd7a3) ||
      (code >= 0xf900 && code <= 0xfaff) ||
      (code >= 0xfe30 && code <= 0xfe4f) ||
      (code >= 0xff00 && code <= 0xff60) ||
      (code >= 0x20000 && code <= 0x3fffd)
        ? 2
        : 1;
  }
  return units;
}

/**
 * Length-based first guess (used before layout exists, e.g. jsdom/SSR, and as
 * the measuring start point so long titles need few reflows). ``capacity`` is
 * how many Latin units fit on two lines at full size.
 */
export function initialScaleIndex(text: string, capacity = 40): number {
  const units = titleWidthUnits(text);
  let index = 0;
  while (
    index < FIT_TEXT_SCALES.length - 1 &&
    units > capacity / FIT_TEXT_SCALES[index]
  ) {
    index += 1;
  }
  return index;
}

/**
 * Pick the largest scale that fits. ``fits(scale)`` applies the scale and
 * reports whether the text fits. Starts at ``start`` and walks up while it
 * still fits, or down until it fits; never more than the step count of checks.
 */
export function pickFitScale(
  fits: (scale: number) => boolean,
  start = 0,
  scales: readonly number[] = FIT_TEXT_SCALES,
): number {
  let index = Math.min(Math.max(start, 0), scales.length - 1);
  if (fits(scales[index])) {
    while (index > 0 && fits(scales[index - 1])) index -= 1;
  } else {
    while (index < scales.length - 1 && !fits(scales[index + 1])) index += 1;
    if (index < scales.length - 1) index += 1;
  }
  return scales[index];
}

function overflows(el: HTMLElement) {
  return (
    el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1
  );
}

/**
 * Attach to the title element. Fits synchronously before paint (no layout
 * shift) and again only when the element's box width changes (ResizeObserver,
 * coalesced to one animation frame; no per-frame loop).
 */
export function useFitText<T extends HTMLElement>(text: string) {
  const ref = useRef<T | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    let base = 0;
    const apply = (scale: number) => {
      el.style.fontSize =
        scale === 1 ? "" : base ? `${base * scale}px` : `${scale}em`;
    };
    const fit = () => {
      el.style.fontSize = "";
      base = parseFloat(getComputedStyle(el).fontSize) || 0;
      // No layout (jsdom/hidden): fall back to the length-based step.
      if (el.clientWidth === 0 && el.clientHeight === 0) {
        apply(FIT_TEXT_SCALES[initialScaleIndex(text)]);
        return;
      }
      const chosen = pickFitScale((scale) => {
        apply(scale);
        return !overflows(el);
      }, initialScaleIndex(text));
      apply(chosen);
      el.dataset.fitScale = String(chosen);
    };
    fit();
    if (typeof ResizeObserver === "undefined") return;
    let frame = 0;
    const box = el.parentElement ?? el;
    let lastWidth = box.clientWidth;
    const observer = new ResizeObserver(() => {
      if (box.clientWidth === lastWidth) return;
      lastWidth = box.clientWidth;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(fit);
    });
    observer.observe(box);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [text]);
  return ref;
}
