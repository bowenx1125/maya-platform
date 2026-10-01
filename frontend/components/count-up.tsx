"use client";

import { useLayoutEffect, useRef } from "react";

import { usePrefersReducedMotion } from "./academy/motion";

const DURATION_MS = 900;

/**
 * A count that runs up to its value when it first appears, so the home's
 * numbers read as tallied rather than printed.
 *
 * React always renders the final value; the run is written straight into the
 * node before paint, so there is no re-render per frame and nothing to undo
 * when motion is reduced or matchMedia is missing (tests, old browsers).
 */
export function CountUp({ value }: { value: number }) {
  const reduced = usePrefersReducedMotion();
  const node = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const element = node.current;
    if (!element) return;
    // Writing the node detaches the text React rendered, so every run ends by
    // writing the value back, including the runs that do not animate.
    if (reduced || value === 0 || typeof window.matchMedia !== "function") {
      element.textContent = String(value);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / DURATION_MS);
      // Ease out: most of the count lands early and the last digits settle.
      element.textContent = String(
        Math.round(value * (1 - (1 - progress) ** 3)),
      );
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    element.textContent = "0";
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      element.textContent = String(value);
    };
  }, [reduced, value]);

  return <span ref={node}>{value}</span>;
}
