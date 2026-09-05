"use client";

import { useEffect, useRef, useState } from "react";

import styles from "./stage3d.module.css";

export type BarrageBullet = {
  id: string;
  nickname: string;
  text: string;
};

export type BarrageLaneProps = {
  /** Every barrage received so far, oldest first. */
  bullets: BarrageBullet[];
  paused: boolean;
  label: string;
};

/**
 * Four lanes across the top third, so a bullet never crosses the speech bubble
 * or the name plates below it.
 */
const LANE_COUNT = 4;
/** On screen at once. Anything beyond this waits rather than stacking. */
const MAX_ON_SCREEN = 12;
/** A bullet a whole classroom can read while it crosses. */
const MAX_TEXT = 56;
const MAX_NICKNAME = 12;
const MIN_LANE_GAP_MS = 900;

type ActiveBullet = BarrageBullet & {
  lane: number;
  durationMs: number;
};

function truncate(value: string, limit: number): string {
  const text = value.trim().replace(/\s+/g, " ");
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

/** A stable per-message speed, so the same bullet never changes pace on rerender. */
function durationFor(id: string): number {
  let hash = 0;
  for (let index = 0; index < id.length; index += 1) {
    hash = (hash * 31 + id.charCodeAt(index)) | 0;
  }
  return 11_000 + (Math.abs(hash) % 5_000);
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function BarrageLane({ bullets, paused, label }: BarrageLaneProps) {
  const [reduced] = useState(prefersReducedMotion);
  const [active, setActive] = useState<ActiveBullet[]>([]);
  const queueRef = useRef<BarrageBullet[]>([]);
  const seenRef = useRef<Set<string>>(new Set());
  const laneFreeAtRef = useRef<number[]>(Array(LANE_COUNT).fill(0));

  // New arrivals queue; they are only admitted when a lane is actually free,
  // which is what keeps a burst of twenty messages from becoming one unreadable
  // block of overlapping text.
  useEffect(() => {
    const seen = seenRef.current;
    const arrived = bullets.filter((bullet) => !seen.has(bullet.id));
    if (!arrived.length) return;
    for (const bullet of arrived) seen.add(bullet.id);
    queueRef.current = [...queueRef.current, ...arrived];
  }, [bullets]);

  useEffect(() => {
    if (reduced || paused) return undefined;
    const timer = window.setInterval(() => {
      setActive((current) => {
        if (!queueRef.current.length || current.length >= MAX_ON_SCREEN) {
          return current;
        }
        const now = Date.now();
        const freeAt = laneFreeAtRef.current;
        let lane = -1;
        for (let index = 0; index < LANE_COUNT; index += 1) {
          if (
            freeAt[index] <= now &&
            (lane === -1 || freeAt[index] < freeAt[lane])
          ) {
            lane = index;
          }
        }
        if (lane === -1) return current;
        const next = queueRef.current.shift();
        if (!next) return current;
        freeAt[lane] = now + MIN_LANE_GAP_MS;
        return [
          ...current,
          { ...next, lane, durationMs: durationFor(next.id) },
        ];
      });
    }, 260);
    return () => window.clearInterval(timer);
  }, [paused, reduced]);

  // Reduced motion still shows the messages: the newest few sit still in the
  // lanes instead of travelling across them.
  const shown = reduced ? bullets.slice(-LANE_COUNT) : active;

  return (
    <div aria-label={label} className={styles.barrage} data-paused={paused}>
      {reduced
        ? shown.map((bullet, index) => (
            <span
              className={styles.bulletStatic}
              key={bullet.id}
              style={{ top: `${8 + index * 34}px` }}
            >
              <b>{truncate(bullet.nickname, MAX_NICKNAME)}</b>
              {truncate(bullet.text, MAX_TEXT)}
            </span>
          ))
        : (shown as ActiveBullet[]).map((bullet) => (
            <span
              className={styles.bullet}
              key={bullet.id}
              onAnimationEnd={() =>
                setActive((current) =>
                  current.filter((item) => item.id !== bullet.id),
                )
              }
              style={{
                top: `${8 + bullet.lane * 34}px`,
                animationDuration: `${bullet.durationMs}ms`,
                animationPlayState: paused ? "paused" : "running",
              }}
            >
              <b>{truncate(bullet.nickname, MAX_NICKNAME)}</b>
              {truncate(bullet.text, MAX_TEXT)}
            </span>
          ))}
    </div>
  );
}
