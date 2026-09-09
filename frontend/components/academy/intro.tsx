"use client";

import { useEffect, useState } from "react";

import { useSession } from "../session-provider";
import { usePrefersReducedMotion } from "./motion";
import { AcademyEmblem } from "./scene";

/**
 * How long the opening sequence takes to play once. The plate is never
 * revealed before this, so the mark has time to be read rather than snapping
 * shut.
 */
const SEQUENCE_MS = 1750;
/** Fade-out, kept in step with the keyframes in globals.css. */
const FAREWELL_MS = 420;

// The four scholars' pigments, so the blocks that fall are recognisably the
// same cast the illustration is about to show.
const BLOCKS = ["#8f7bb5", "#c2704f", "#6f9b7d", "#d8a94b"];

/**
 * Entrance animation, and the loading screen.
 *
 * The mark collapses to a point and four blocks drop in its place. Those
 * blocks then keep bouncing for as long as the session is still resolving, so
 * on a slow connection this is what the viewer watches instead of a
 * half-painted form. It leaves once the app is ready *and* the sequence has
 * played, so a fast load still gets the whole animation rather than a flash.
 *
 * The mark is whatever `AcademyEmblem` draws, so dropping in a real product
 * logo changes this screen with nothing to update here.
 */
export function AcademyIntro() {
  const reduced = usePrefersReducedMotion();
  const { status } = useSession();
  const [played, setPlayed] = useState(false);
  const [gone, setGone] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setPlayed(true), SEQUENCE_MS);
    return () => window.clearTimeout(timer);
  }, []);

  // Derived rather than stored: as state it belonged in the same effect that
  // schedules the unmount, and the re-run then cancelled its own timer.
  const leaving = played && status !== "loading";

  useEffect(() => {
    if (!leaving) return;
    const timer = window.setTimeout(() => setGone(true), FAREWELL_MS);
    return () => window.clearTimeout(timer);
  }, [leaving]);

  // Decorative throughout: the page behind it is already rendered and
  // reachable, and a viewer who asked for reduced motion never sees it.
  if (reduced || gone) return null;
  return (
    <div
      className="academy-intro"
      data-leaving={leaving ? "true" : undefined}
      aria-hidden="true"
    >
      <span className="academy-intro-mark">
        <AcademyEmblem />
      </span>
      <span className="academy-intro-blocks">
        {BLOCKS.map((colour, index) => (
          <i
            key={colour}
            style={{
              background: colour,
              animationDelay: `${0.78 + index * 0.09}s, ${1.6 + index * 0.11}s`,
            }}
          />
        ))}
      </span>
    </div>
  );
}
