"use client";

/**
 * The Mayaform mark: a gold ring with an indigo disc set above and right of it.
 *
 * This is the same shape `.brand-dot` draws in the signed-in header, at the
 * proportions that rule sets — a 3-in-18 ring, a 16-wide disc offset by 5 and
 * -4 — so the logo the opening animation collapses is the one the app then
 * wears in its nav.  The viewBox is cropped to the mark itself rather than
 * padded to a square, which lets it scale without a margin of empty space.
 */
export function AcademyEmblem() {
  return (
    <svg
      className="academy-emblem"
      viewBox="0 0 66 63"
      aria-hidden="true"
      focusable="false"
    >
      {/* Drawn first, so the ring crosses in front of it as the shadow does. */}
      <circle cx="42" cy="24" r="24" fill="var(--indigo)" />
      <circle
        cx="27"
        cy="36"
        r="22.5"
        fill="none"
        stroke="var(--gold)"
        strokeWidth="9"
      />
    </svg>
  );
}
