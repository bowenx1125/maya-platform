"use client";

import { useEffect, useState } from "react";

import { usePrefersReducedMotion } from "./motion";
import { AcademyEmblem } from "./scene";

/** Total run time; must stay in step with the keyframes in globals.css. */
const RUN_MS = 1900;

// The four scholars' pigments, so the blocks that fall are recognisably the
// same cast the illustration is about to show.
const BLOCKS = ["#8f7bb5", "#c2704f", "#6f9b7d", "#d8a94b"];

/**
 * Entrance animation: the mark collapses to a point, four blocks drop and
 * bounce into place, and the plate is revealed.
 *
 * The mark is whatever `AcademyEmblem` draws, so replacing the emblem with a
 * real product logo changes this screen too, with nothing to update here.
 */
export function AcademyIntro() {
  const reduced = usePrefersReducedMotion();
  const [elapsed, setElapsed] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setElapsed(true), RUN_MS);
    return () => window.clearTimeout(timer);
  }, []);

  // Decorative throughout: the page behind it is already rendered and
  // reachable, and a viewer who asked for reduced motion never sees it. The
  // preference is read at render rather than pushed into state, so no effect
  // has to write state synchronously to honour it.
  if (reduced || elapsed) return null;
  return (
    <div className="academy-intro" aria-hidden="true">
      <span className="academy-intro-mark">
        <AcademyEmblem />
      </span>
      <span className="academy-intro-blocks">
        {BLOCKS.map((colour, index) => (
          <i
            key={colour}
            style={{
              background: colour,
              animationDelay: `${0.5 + index * 0.08}s`,
            }}
          />
        ))}
      </span>
    </div>
  );
}
