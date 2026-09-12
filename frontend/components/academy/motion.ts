"use client";

import { useEffect, useState } from "react";

/**
 * Whether the viewer has asked for reduced motion.
 *
 * Shared by the mascots and the entrance animation so both opt out together:
 * a page that skips the intro but still tracks the cursor would be a partial
 * answer to the same preference.
 */
export function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);
  return reduced;
}
