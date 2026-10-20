"use client";

import { useFitText } from "../lib/fit-text";

/**
 * The text inside a title button. The button keeps its size tier (one line
 * minimum, two lines maximum); this span clamps to two lines and its font
 * shrinks in steps until the whole title fits.
 */
export function FitTitle({
  text,
  className = "fit-title-text",
}: {
  text: string;
  className?: string;
}) {
  const ref = useFitText<HTMLSpanElement>(text);
  return (
    <span ref={ref} className={className}>
      {text}
    </span>
  );
}
