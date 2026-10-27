"use client";

import { useEffect, useId, useRef } from "react";

import { useAcademyMood, type AcademyMood } from "./mood";
import { usePrefersReducedMotion } from "./motion";

const VIEW_W = 440;
const VIEW_H = 214;
/** Shared ground line. The four differ in size, not in where they stand. */
const FLOOR = 188;
const PUPIL_REACH = 5.2;
/** Fraction of the remaining distance covered per frame. */
const EASE = 0.2;

type Accessory = "scroll" | "wreath" | "tablet" | "wave";
/** Not every scholar is a block; the group reads better with four outlines. */
type Shape = "block" | "round" | "arch" | "pillar";

type Scholar = {
  id: string;
  cx: number;
  w: number;
  h: number;
  shape: Shape;
  body: string;
  shade: string;
  accessory: Accessory;
  /** Fraction of the shared turn, so the four do not move in lockstep. */
  lag: number;
  /** Idle breathing period; different for each so they never sync up. */
  bob: string;
  /** How this one hides while a password is on screen. */
  turn: number;
  duck: number;
  /** Offset so the four do not react in unison. */
  stagger: string;
};

// Muted fresco pigments rather than saturated UI colours, and four different
// builds: tall and narrow, short and wide, round, and a thin column.
const SCHOLARS: Scholar[] = [
  {
    id: "scroll",
    cx: 80,
    w: 64,
    h: 92,
    shape: "arch",
    body: "#8f7bb5",
    shade: "#7b66a4",
    accessory: "scroll",
    lag: 1,
    bob: "3.4s",
    turn: -17,
    duck: 3,
    stagger: "0ms",
  },
  {
    id: "wreath",
    cx: 160,
    w: 88,
    h: 74,
    shape: "block",
    body: "#c2704f",
    shade: "#ab5f42",
    accessory: "wreath",
    lag: 0.88,
    bob: "4.1s",
    turn: 9,
    duck: 6,
    stagger: "70ms",
  },
  {
    id: "tablet",
    cx: 258,
    w: 70,
    h: 70,
    shape: "round",
    body: "#6f9b7d",
    shade: "#5e876b",
    accessory: "tablet",
    lag: 0.95,
    bob: "3.7s",
    turn: -6,
    duck: -4,
    stagger: "140ms",
  },
  {
    id: "wave",
    cx: 358,
    w: 56,
    h: 104,
    shape: "pillar",
    body: "#d8a94b",
    shade: "#c2953a",
    accessory: "wave",
    lag: 0.82,
    bob: "4.6s",
    turn: 14,
    duck: 2,
    stagger: "40ms",
  },
];

/**
 * Round a derived coordinate.
 *
 * Server and client can serialise the same double to strings that differ in
 * the last digit, which React reports as a hydration mismatch. Fixing the
 * precision removes that, and keeps the emitted path data readable.
 */
function round(value: number) {
  return Math.round(value * 100) / 100;
}

/** Rounded rectangle with per-corner radii, as an SVG path. */
function bodyPath(
  shape: Shape,
  left: number,
  top: number,
  w: number,
  h: number,
) {
  const cap = (radius: number) => Math.min(radius, w / 2, h / 2);
  const [tl, tr, br, bl] = (
    shape === "round"
      ? [w / 2, w / 2, w / 2, w / 2].map(cap)
      : shape === "arch"
        ? [cap(w / 2), cap(w / 2), 10, 10]
        : shape === "pillar"
          ? [cap(w * 0.16), cap(w * 0.16), cap(w * 0.16), cap(w * 0.16)]
          : [w * 0.27, w * 0.27, w * 0.27, w * 0.27].map(cap)
  ).map(round);
  const right = left + w;
  const bottom = top + h;
  return [
    `M${left + tl} ${top}`,
    `H${right - tr}`,
    `A${tr} ${tr} 0 0 1 ${right} ${top + tr}`,
    `V${bottom - br}`,
    `A${br} ${br} 0 0 1 ${right - br} ${bottom}`,
    `H${left + bl}`,
    `A${bl} ${bl} 0 0 1 ${left} ${bottom - bl}`,
    `V${top + tl}`,
    `A${tl} ${tl} 0 0 1 ${left + tl} ${top}`,
    "Z",
  ].join(" ");
}

type Geometry = {
  top: number;
  left: number;
  right: number;
  eyeY: number;
  eyeDx: number;
  eyeR: number;
};

function geometryFor(scholar: Scholar): Geometry {
  const top = FLOOR - scholar.h;
  // Proportional rather than fixed, so the smallest scholar does not end up
  // wearing the same face as the largest.
  return {
    top,
    left: round(scholar.cx - scholar.w / 2),
    right: round(scholar.cx + scholar.w / 2),
    eyeY: round(top + scholar.h * 0.36),
    eyeDx: round(Math.min(scholar.w * 0.22, 17)),
    eyeR: round(5.6 + scholar.w * 0.035),
  };
}

type Point = { x: number; y: number };

function pupilTarget(
  scholar: Scholar,
  mood: AcademyMood,
  pointer: Point | null,
): Point {
  // Looking away is the whole point of the discreet mood; the eyes are drawn
  // closed, so the offset is irrelevant.
  if (mood === "discreet") return { x: 0, y: 0 };
  // While a field is being filled in, every scholar turns towards the form
  // rather than towards the cursor.
  if (mood === "attentive") return { x: PUPIL_REACH, y: -0.8 };
  if (!pointer) return { x: 0, y: 0 };
  const { eyeY } = geometryFor(scholar);
  const dx = pointer.x - scholar.cx;
  const dy = pointer.y - eyeY;
  const distance = Math.hypot(dx, dy) || 1;
  // Ease the reach so a far-away cursor does not peg the pupils at the rim.
  const reach = Math.min(distance / 100, 1) * PUPIL_REACH * scholar.lag;
  return { x: (dx / distance) * reach, y: (dy / distance) * reach };
}

/**
 * Drive the pupils straight from an animation frame rather than from React
 * state.
 *
 * A `setState` per mousemove re-renders every scholar, which is what made the
 * eyes lag behind the cursor. Here the pointer and the current offsets live in
 * refs, one frame writes four transforms, and the loop stops as soon as the
 * eyes have caught up, so an idle page costs nothing.
 */
function useEyeTracking(
  svgRef: React.RefObject<SVGSVGElement | null>,
  mood: AcademyMood,
  enabled: boolean,
) {
  const nodes = useRef<Record<string, SVGGElement | null>>({});
  const pointer = useRef<Point | null>(null);
  const current = useRef<Record<string, Point>>({});
  const moodRef = useRef(mood);
  const kick = useRef<() => void>(() => undefined);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    let frame = 0;

    function step() {
      frame = 0;
      let settling = false;
      for (const scholar of SCHOLARS) {
        const node = nodes.current[scholar.id];
        if (!node) continue;
        const target = pupilTarget(scholar, moodRef.current, pointer.current);
        const from = current.current[scholar.id] ?? { x: 0, y: 0 };
        const next = {
          x: from.x + (target.x - from.x) * EASE,
          y: from.y + (target.y - from.y) * EASE,
        };
        current.current[scholar.id] = next;
        node.style.transform = `translate(${next.x.toFixed(2)}px, ${next.y.toFixed(2)}px)`;
        if (Math.abs(target.x - next.x) + Math.abs(target.y - next.y) > 0.04) {
          settling = true;
        }
      }
      // Stop as soon as the eyes have caught up: an untouched page should not
      // hold an animation frame open.
      if (settling) frame = window.requestAnimationFrame(step);
    }

    function start() {
      if (!frame) frame = window.requestAnimationFrame(step);
    }

    function onMove(event: MouseEvent) {
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      pointer.current = {
        x: ((event.clientX - rect.left) / rect.width) * VIEW_W,
        y: ((event.clientY - rect.top) / rect.height) * VIEW_H,
      };
      start();
    }

    kick.current = start;
    window.addEventListener("mousemove", onMove, { passive: true });
    start();
    return () => {
      window.removeEventListener("mousemove", onMove);
      if (frame) window.cancelAnimationFrame(frame);
      kick.current = () => undefined;
    };
  }, [enabled, svgRef]);

  useEffect(() => {
    moodRef.current = mood;
    kick.current();
  }, [mood]);

  return nodes;
}

function Accessory({
  scholar,
  geometry,
  mood,
}: {
  scholar: Scholar;
  geometry: Geometry;
  mood: AcademyMood;
}) {
  const { cx, body, shade, h } = scholar;
  const { top, left, right } = geometry;
  // Arms are drawn in the body colour so a held object reads as held rather
  // than as a shape floating beside the block.
  const arm = {
    stroke: body,
    strokeWidth: 8.5,
    strokeLinecap: "round" as const,
    fill: "none",
  };
  const handY = round(top + h * 0.6);

  switch (scholar.accessory) {
    case "wreath":
      // Headwear is drawn in front of the body; see HeadPiece.
      return null;
    case "scroll":
      return (
        <g>
          <path d={`M${left + 7} ${handY - 4} q-17 10 -21 21`} {...arm} />
          <g transform={`rotate(-14 ${left - 21} ${handY + 26})`}>
            {/* Sheet first, then the rolled ends over it, so the roll reads as
                wrapped around the paper. */}
            <rect
              x={left - 32}
              y={handY + 12}
              width="23"
              height="29"
              fill="#f7efdd"
              stroke="#c9a227"
              strokeWidth="1.6"
            />
            <g stroke={shade} strokeWidth="1.5" strokeLinecap="round">
              <path d={`M${left - 28} ${handY + 20} h15`} />
              <path d={`M${left - 28} ${handY + 26} h15`} />
              <path d={`M${left - 28} ${handY + 32} h10`} />
            </g>
            <rect
              x={left - 36}
              y={handY + 6}
              width="31"
              height="9"
              rx="4.5"
              fill="#e8dcc0"
              stroke="#c9a227"
              strokeWidth="1.8"
            />
            <rect
              x={left - 36}
              y={handY + 38}
              width="31"
              height="9"
              rx="4.5"
              fill="#e8dcc0"
              stroke="#c9a227"
              strokeWidth="1.8"
            />
          </g>
        </g>
      );
    case "tablet":
      return (
        <g>
          <path d={`M${right - 7} ${handY - 4} q17 8 22 18`} {...arm} />
          <rect
            x={right + 5}
            y={handY + 4}
            width="25"
            height="30"
            rx="4"
            fill="#efe4cd"
            stroke="#a98a52"
            strokeWidth="2"
            transform={`rotate(12 ${right + 17} ${handY + 19})`}
          />
        </g>
      );
    case "wave": {
      // While a password is on screen the raised arm comes across the face
      // instead of waving: one of the four hides differently from the rest.
      const hiding = mood === "discreet";
      const elbow = hiding
        ? `M${right - 7} ${handY - 8} q18 -22 -6 -34`
        : `M${right - 7} ${handY - 8} q21 -6 25 -31`;
      return (
        <g
          className="academy-wave-arm"
          // Pivot at the shoulder, or the arm swings around the SVG origin.
          style={{ transformOrigin: `${right - 7}px ${handY - 8}px` }}
        >
          <path d={elbow} {...arm} />
          <circle
            cx={hiding ? cx + 6 : right + 17}
            cy={hiding ? top + 18 : top + 12}
            r="7"
            fill={body}
          />
        </g>
      );
    }
  }
}

function HeadPiece({
  scholar,
  geometry,
}: {
  scholar: Scholar;
  geometry: Geometry;
}) {
  const { cx } = scholar;
  const { top } = geometry;
  if (scholar.accessory !== "wreath") return null;

  // Leaves seated on the crown rather than hovering over it: the arc's centre
  // is pushed down so the lowest leaves rest against the head.
  const leaves = [-58, -38, -19, 19, 38, 58].map((angle) => {
    const radians = (angle * Math.PI) / 180;
    return {
      angle,
      x: round(cx + Math.sin(radians) * 38),
      y: round(top + 21 - Math.cos(radians) * 22),
    };
  });
  return (
    <g>
      <path
        d={`M${cx - 33} ${top + 20} q33 -26 66 0`}
        fill="none"
        stroke="#c9a227"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      {leaves.map((leaf) => (
        <ellipse
          key={leaf.angle}
          cx={leaf.x}
          cy={leaf.y}
          rx="7"
          ry="3.4"
          fill="#cfae3d"
          transform={`rotate(${leaf.angle} ${leaf.x} ${leaf.y})`}
        />
      ))}
    </g>
  );
}

function Scholar({
  scholar,
  mood,
  pupilRef,
  still = false,
  clipKey = "",
}: {
  scholar: Scholar;
  mood: AcademyMood;
  pupilRef: (node: SVGGElement | null) => void;
  /** A static portrait (cards, notices, guide): no bobbing, no eye tracking,
   * and none of the `.academy-scholar` hooks the home easter egg queries. */
  still?: boolean;
  clipKey?: string;
}) {
  const { cx, body, shade, w, h } = scholar;
  const geometry = geometryFor(scholar);
  const { top, left, right, eyeY, eyeDx, eyeR } = geometry;
  const closed = mood === "discreet";
  const outline = bodyPath(scholar.shape, left, top, w, h);
  const clipId = `academy-body-${scholar.id}${clipKey}`;
  const hem = round(top + h * 0.62);
  const footY = FLOOR - 1;

  return (
    <g
      className={still ? undefined : "academy-scholar"}
      data-scholar={still ? undefined : scholar.id}
      data-shape={scholar.shape}
      data-height={h}
      data-width={w}
      style={
        still
          ? undefined
          : ({
              "--bob": scholar.bob,
              "--stagger": scholar.stagger,
              transform: closed
                ? `rotate(${scholar.turn}deg) translate(0px, ${scholar.duck}px)`
                : undefined,
              transformOrigin: `${cx}px ${FLOOR}px`,
            } as React.CSSProperties)
      }
    >
      <ellipse
        className="academy-shadow"
        cx={cx}
        cy={FLOOR + 9}
        rx={round(w * 0.46)}
        ry="6"
        fill="#c9b79a"
        opacity="0.38"
      />
      {/* Inner group carries the idle breathing and the squash on a mood
          change, so it composes with the turn on the group above. */}
      <g
        className={still ? undefined : "academy-jelly"}
        style={{ transformOrigin: `${cx}px ${FLOOR}px` }}
      >
        <Accessory scholar={scholar} geometry={geometry} mood={mood} />
        <clipPath id={clipId}>
          <path d={outline} />
        </clipPath>
        <path className="academy-block" d={outline} fill={body} />
        <HeadPiece scholar={scholar} geometry={geometry} />
        {/* The toga is clipped to the body outline, so a domed or round
            scholar gets a drape that follows its own silhouette. */}
        <g clipPath={`url(#${clipId})`}>
          <path
            d={`M${left - 2} ${hem} L${right + 2} ${hem - 16} L${right + 2} ${FLOOR + 2} L${left - 2} ${FLOOR + 2} Z`}
            fill="#f6f0e4"
          />
          <path
            d={`M${left - 2} ${hem} L${right + 2} ${hem - 16}`}
            stroke="#c9a227"
            strokeWidth="2.5"
            fill="none"
          />
        </g>
        <rect x={cx - 12} y={footY} width="9" height="7" rx="3" fill={shade} />
        <rect x={cx + 3} y={footY} width="9" height="7" rx="3" fill={shade} />

        {closed ? (
          <g
            stroke="#2f2a22"
            strokeWidth="2.6"
            strokeLinecap="round"
            fill="none"
          >
            <path d={`M${cx - eyeDx - 6} ${eyeY} q6 5 12 0`} />
            <path d={`M${cx + eyeDx - 6} ${eyeY} q6 5 12 0`} />
          </g>
        ) : (
          <g>
            <circle cx={cx - eyeDx} cy={eyeY} r={eyeR} fill="#fffdf8" />
            <circle cx={cx + eyeDx} cy={eyeY} r={eyeR} fill="#fffdf8" />
            <g className="academy-pupils" ref={pupilRef}>
              <circle
                className="academy-pupil"
                cx={cx - eyeDx}
                cy={eyeY}
                r={round(eyeR * 0.5)}
                fill="#2f2a22"
              />
              <circle
                className="academy-pupil"
                cx={cx + eyeDx}
                cy={eyeY}
                r={round(eyeR * 0.5)}
                fill="#2f2a22"
              />
            </g>
          </g>
        )}
        <path
          d={
            mood === "refused"
              ? `M${cx - 7} ${eyeY + 19} q7 -6 14 0`
              : `M${cx - 7} ${eyeY + 16} q7 6 14 0`
          }
          stroke="#2f2a22"
          strokeWidth="2.4"
          strokeLinecap="round"
          fill="none"
        />
      </g>
    </g>
  );
}

export function AcademyMascots({ label }: { label: string }) {
  const mood = useAcademyMood();
  const reduced = usePrefersReducedMotion();
  const ref = useRef<SVGSVGElement>(null);
  const nodes = useEyeTracking(ref, mood, !reduced);

  return (
    <svg
      ref={ref}
      className="academy-mascots"
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      role="img"
      aria-label={label}
      data-mood={mood}
      data-reduced={reduced ? "true" : undefined}
    >
      {SCHOLARS.map((scholar) => (
        <Scholar
          key={scholar.id}
          scholar={scholar}
          mood={mood}
          pupilRef={(node) => {
            nodes.current[scholar.id] = node;
          }}
        />
      ))}
    </svg>
  );
}

export type MascotId = "scroll" | "wreath" | "tablet" | "wave";

export const MASCOT_IDS: readonly MascotId[] = [
  "scroll",
  "wreath",
  "tablet",
  "wave",
];

/**
 * One scholar on its own, standing still: the Agent card avatar, the notice
 * tray speaker and the guide portrait. Decorative (aria-hidden); it carries no
 * `.academy-scholar` class, so the home easter egg never picks it up.
 */
export function MascotFigure({
  id,
  className,
  mood = "idle",
}: {
  id: MascotId;
  className?: string;
  /** A held pose (sign-in mockups); the figure never animates on its own. */
  mood?: AcademyMood;
}) {
  const clipKey = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const scholar = SCHOLARS.find((item) => item.id === id) ?? SCHOLARS[3];
  const { top, left } = geometryFor(scholar);
  const padX = 30;
  const x = round(left - padX);
  const y = round(top - 26);
  const width = round(scholar.w + padX * 2);
  const height = round(FLOOR + 17 - y);
  return (
    <svg
      className={className}
      viewBox={`${x} ${y} ${width} ${height}`}
      aria-hidden="true"
      focusable="false"
      data-mascot={scholar.id}
    >
      <Scholar
        scholar={scholar}
        mood={mood}
        pupilRef={() => undefined}
        still
        clipKey={`-${clipKey}`}
      />
    </svg>
  );
}
