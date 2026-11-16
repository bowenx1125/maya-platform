"use client";

import { useEffect, useState } from "react";

export type LoaderSize = "lg" | "sm" | "xs";

/**
 * The one loading look (loading-v3 agent-2, chosen 2026-11-04): the ghost
 * agent bobs in place above a pixel bar whose segments light in turn.
 * Decorative only; the caller owns role/aria and the label text.
 *
 * Voices uses count=3: three larger ghosts side by side with staggered
 * hops so they do not bob in sync. Every other page stays count=1.
 */
export function AgentLoader({
  size = "lg",
  label,
  count = 1,
}: {
  size?: LoaderSize;
  label?: string;
  /** Number of ghost agents (Voices large uses 3). */
  count?: number;
}) {
  const agents = Math.max(1, Math.min(6, Math.floor(count)));
  const multi = agents > 1;
  const segments = size === "lg" || multi ? 10 : 6;
  // Stagger so neighbors never land on the same frame of the 0.8s hop.
  const stagger = 0.22;
  return (
    <span className={`ag a2 ${size}${multi ? " multi" : ""}`}>
      <span className="track" aria-hidden="true">
        {Array.from({ length: agents }, (_, index) => (
          <span
            key={index}
            className="agent"
            style={
              multi
                ? { animationDelay: `${(index * stagger).toFixed(2)}s` }
                : undefined
            }
          />
        ))}
      </span>
      <span className="bar" aria-hidden="true">
        {Array.from({ length: segments }, (_, index) => (
          <i
            key={index}
            style={{
              animationDelay: `${((index * 2.2) / segments).toFixed(2)}s`,
            }}
          />
        ))}
      </span>
      {label ? <span className="lbl">{label}</span> : null}
    </span>
  );
}

/**
 * Stage loading (loading-v3 stage-B): pink curtains with a yellow valance
 * and the label on a white plate; they open (0.6s) on Start or scene readiness.
 */
export function StageCurtain({
  loading,
  label,
}: {
  loading: boolean;
  label: string;
}) {
  const [shown, setShown] = useState(loading);
  const [opening, setOpening] = useState(!loading);
  if (!loading && !opening) setOpening(true);
  useEffect(() => {
    if (opening) return;
    // Asset downloads may never settle; they must not keep the curtain shut.
    const timer = window.setTimeout(() => setOpening(true), 3000);
    return () => window.clearTimeout(timer);
  }, [opening]);
  useEffect(() => {
    if (!opening || !shown) return;
    const timer = window.setTimeout(() => setShown(false), 600);
    return () => window.clearTimeout(timer);
  }, [opening, shown]);
  if (!shown) return null;
  return (
    <div
      className={opening ? "stage-curtain open" : "stage-curtain"}
      role={opening ? undefined : "status"}
      data-testid="stage-curtain"
    >
      <span className="cur l" aria-hidden="true" />
      <span className="cur r" aria-hidden="true" />
      <span className="val" aria-hidden="true" />
      <span className="val2" aria-hidden="true" />
      <p className="lbl">{label}</p>
    </div>
  );
}
