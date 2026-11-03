"use client";

import { useEffect, useState } from "react";

export type LoaderSize = "lg" | "sm" | "xs";

/**
 * The one loading look (loading-v3 agent-2, chosen 2026-11-04): the ghost
 * agent bobs in place above a pixel bar whose segments light in turn.
 * Decorative only; the caller owns role/aria and the label text.
 */
export function AgentLoader({
  size = "lg",
  label,
}: {
  size?: LoaderSize;
  label?: string;
}) {
  const segments = size === "lg" ? 10 : 6;
  return (
    <span className={`ag a2 ${size}`}>
      <span className="track" aria-hidden="true">
        <span className="agent" />
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
 * and the label on a white plate; they open (0.6s) once the scene is ready.
 */
export function StageCurtain({
  loading,
  label,
}: {
  loading: boolean;
  label: string;
}) {
  const [shown, setShown] = useState(loading);
  if (loading && !shown) setShown(true);
  useEffect(() => {
    if (loading || !shown) return;
    const timer = window.setTimeout(() => setShown(false), 600);
    return () => window.clearTimeout(timer);
  }, [loading, shown]);
  if (!shown) return null;
  return (
    <div
      className={loading ? "stage-curtain" : "stage-curtain open"}
      role={loading ? "status" : undefined}
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
