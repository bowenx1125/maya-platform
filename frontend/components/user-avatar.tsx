import type { CSSProperties } from "react";

export const USER_AVATAR_CHOICES = [
  "scholar-arch:violet",
  "scholar-block:terracotta",
  "scholar-round:sage",
  "scholar-pillar:gold",
  "scholar-arch:gold",
  "scholar-block:violet",
  "scholar-round:terracotta",
  "scholar-pillar:sage",
] as const;

const COLORS = {
  violet: ["#8f7bb5", "#6d5c93"],
  terracotta: ["#c2704f", "#9c5539"],
  sage: ["#6f9b7d", "#547d62"],
  gold: ["#d8a94b", "#ad8028"],
} as const;

type Shape = "arch" | "block" | "round" | "pillar";
type Colour = keyof typeof COLORS;

/**
 * Each scholar is described by its own geometry rather than a hand-drawn path,
 * because everything else on the figure is derived from it. The robe, the sash,
 * the feet and the eyes all read `left`/`right`, so a silhouette can change
 * width without leaving the robe hanging outside the body — which is what made
 * the first four look like smudges at small sizes.
 *
 * The four differ in width, height and how the top is closed, so they stay
 * apart from each other at 24px where a couple of units of corner radius
 * would not.
 */
const SHAPES: Record<Shape, { left: number; right: number; top: number }> = {
  // Broad and flat-shouldered, wearing a scholar's board.
  block: { left: 11, right: 53, top: 15 },
  // A plain dome, the shortest of the four.
  round: { left: 19, right: 45, top: 17 },
  // Tall, narrow and pointed.
  arch: { left: 22, right: 42, top: 6 },
  // A column: straight sides under a flared capital.
  pillar: { left: 17, right: 47, top: 16 },
};

const BASE = 49;
/**
 * Every silhouette has reached its full width well above this line, so the
 * robe drawn from here down is always inside the body and needs no clipping.
 */
const ROBE_TOP = 33;

function bodyPath(shape: Shape) {
  const { left, right, top } = SHAPES[shape];
  const mid = (left + right) / 2;
  if (shape === "round") {
    const radius = (right - left) / 2;
    return `M${left} ${BASE}V${top + radius}a${radius} ${radius} 0 0 1 ${right - left} 0V${BASE}Z`;
  }
  if (shape === "arch") {
    // A gothic point: two curves that meet above the shoulders.
    return `M${left} ${BASE}V${top + 14}Q${left} ${top} ${mid} ${top}Q${right} ${top} ${right} ${top + 14}V${BASE}Z`;
  }
  if (shape === "pillar") {
    return `M${left} ${BASE}V${top + 3}q0 -3 3 -3h${right - left - 6}q3 0 3 3V${BASE}Z`;
  }
  return `M${left} ${BASE}V${top + 8}q0 -8 8 -8h${right - left - 16}q8 0 8 8V${BASE}Z`;
}

function headwear(shape: Shape, shade: string) {
  const { left, right, top } = SHAPES[shape];
  const mid = (left + right) / 2;
  if (shape === "block") {
    // A flat board sitting across the crown, wider than the head itself.
    return (
      <g fill={shade}>
        <rect
          x={left - 3}
          y={top - 5}
          width={right - left + 6}
          height="4"
          rx="2"
        />
        <rect x={mid - 2} y={top - 1} width="4" height="3" />
      </g>
    );
  }
  if (shape === "round") {
    // A laurel band, the quietest of the four.
    return (
      <path
        d={`M${left + 2} ${top + 9}q${mid - left - 2} -7 ${right - left - 4} 0`}
        fill="none"
        stroke={shade}
        strokeWidth="3"
        strokeLinecap="round"
      />
    );
  }
  if (shape === "arch") {
    // A hood drawn over the point.
    return (
      <path
        d={`M${left - 1} ${top + 17}Q${left - 1} ${top - 4} ${mid} ${top - 4}Q${right + 1} ${top - 4} ${right + 1} ${top + 17}Q${mid} ${top + 8} ${left - 1} ${top + 17}Z`}
        fill={shade}
      />
    );
  }
  // A column capital: a slab with a scroll at each end.
  return (
    <g fill={shade}>
      <rect
        x={left - 4}
        y={top - 6}
        width={right - left + 8}
        height="5"
        rx="2"
      />
      <circle cx={left - 1} cy={top - 1} r="2.5" />
      <circle cx={right + 1} cy={top - 1} r="2.5" />
    </g>
  );
}

function avatarSpec(value: string | null | undefined) {
  const match =
    /^scholar-(arch|block|round|pillar):(violet|terracotta|sage|gold)$/.exec(
      value ?? "",
    );
  if (!match) return null;
  return { shape: match[1] as Shape, colour: match[2] as Colour };
}

/**
 * Letter tiles: the same four hues, darkened so the white letter passes
 * WCAG AA (each ≥ 4.6:1 against #fff) at every size.
 */
const FALLBACK_COLORS = [
  ["#8069ab", "#6d5c93"],
  ["#b05e3d", "#9c5539"],
  ["#577d63", "#547d62"],
  ["#956e20", "#ad8028"],
] as const;

function fallbackColour(seed: string) {
  let hash = 0;
  for (const character of seed)
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return FALLBACK_COLORS[hash % FALLBACK_COLORS.length];
}

export function UserAvatar({
  avatar,
  name,
  userId,
  size = "md",
}: {
  avatar?: string | null;
  name: string;
  userId?: string;
  size?: "sm" | "md" | "lg";
}) {
  const spec = avatarSpec(avatar);
  const [body, shade] = spec
    ? COLORS[spec.colour]
    : fallbackColour(userId || name);
  const initial = name.trim().slice(0, 1).toUpperCase() || "?";

  if (!spec) {
    return (
      <span
        className={`user-avatar user-avatar-${size} user-avatar-fallback`}
        role="img"
        aria-label={`${name} avatar`}
        style={{ "--avatar-body": body } as CSSProperties}
      >
        {initial}
      </span>
    );
  }

  const { left, right } = SHAPES[spec.shape];
  const mid = (left + right) / 2;
  const eye = Math.min(6, (right - left) / 4.4);

  return (
    <span className={`user-avatar user-avatar-${size}`}>
      <svg viewBox="0 0 64 64" role="img" aria-label={`${name} avatar`}>
        <ellipse
          cx="32"
          cy={BASE + 3}
          rx={(right - left) / 1.7}
          ry="3"
          fill="#c9b79a"
          opacity=".3"
        />
        <path d={bodyPath(spec.shape)} fill={body} />
        <path
          d={`M${left} ${ROBE_TOP + 7} ${right} ${ROBE_TOP}V${BASE}H${left}Z`}
          fill="#f7f1e7"
        />
        <path
          d={`M${left} ${ROBE_TOP + 7} ${right} ${ROBE_TOP}`}
          fill="none"
          stroke="#d3a74a"
          strokeWidth="2"
        />
        <rect
          x={mid - 9}
          y={BASE - 4}
          width="6"
          height="5"
          rx="2.5"
          fill={shade}
        />
        <rect
          x={mid + 3}
          y={BASE - 4}
          width="6"
          height="5"
          rx="2.5"
          fill={shade}
        />
        {/* Drawn after the body so a hood or a board is never painted over. */}
        {headwear(spec.shape, shade)}
        <circle
          cx={mid - eye}
          cy={ROBE_TOP - 8}
          r={eye * 0.85}
          fill="#fffdf8"
        />
        <circle
          cx={mid + eye}
          cy={ROBE_TOP - 8}
          r={eye * 0.85}
          fill="#fffdf8"
        />
        <circle
          cx={mid - eye + 0.6}
          cy={ROBE_TOP - 7.4}
          r={eye * 0.36}
          fill="#27233d"
        />
        <circle
          cx={mid + eye + 0.6}
          cy={ROBE_TOP - 7.4}
          r={eye * 0.36}
          fill="#27233d"
        />
        <path
          d={`M${mid - 4} ${ROBE_TOP - 1}q4 3.5 8 0`}
          fill="none"
          stroke="#27233d"
          strokeLinecap="round"
          strokeWidth="1.8"
        />
      </svg>
    </span>
  );
}
