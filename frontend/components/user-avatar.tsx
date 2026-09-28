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
  violet: ["#8f7bb5", "#75629d"],
  terracotta: ["#c2704f", "#a95d40"],
  sage: ["#6f9b7d", "#588268"],
  gold: ["#d8a94b", "#b98b32"],
} as const;

type Shape = "arch" | "block" | "round" | "pillar";
type Colour = keyof typeof COLORS;

function avatarSpec(value: string | null | undefined) {
  const match =
    /^scholar-(arch|block|round|pillar):(violet|terracotta|sage|gold)$/.exec(
      value ?? "",
    );
  if (!match) return null;
  return { shape: match[1] as Shape, colour: match[2] as Colour };
}

function fallbackColour(seed: string) {
  let hash = 0;
  for (const character of seed)
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return Object.values(COLORS)[hash % Object.keys(COLORS).length];
}

function bodyPath(shape: Shape) {
  if (shape === "round") return "M16 29a16 16 0 1 1 32 0v17H16Z";
  if (shape === "arch") return "M15 29a17 17 0 0 1 34 0v18H15Z";
  if (shape === "pillar")
    return "M20 12h24a5 5 0 0 1 5 5v30H15V17a5 5 0 0 1 5-5Z";
  return "M14 17a8 8 0 0 1 8-8h20a8 8 0 0 1 8 8v30H14Z";
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

  return (
    <span className={`user-avatar user-avatar-${size}`}>
      <svg viewBox="0 0 64 64" role="img" aria-label={`${name} avatar`}>
        <ellipse cx="32" cy="56" rx="20" ry="4" fill="#c9b79a" opacity=".34" />
        <path d={bodyPath(spec.shape)} fill={body} />
        <path d="M14 39 50 31v17H14Z" fill="#f7f1e7" />
        <path d="M14 39 50 31" fill="none" stroke="#d3a74a" strokeWidth="2" />
        <circle cx="25" cy="27" r="5" fill="#fffdf8" />
        <circle cx="39" cy="27" r="5" fill="#fffdf8" />
        <circle cx="26" cy="28" r="2" fill="#27233d" />
        <circle cx="40" cy="28" r="2" fill="#27233d" />
        <path
          d="M27 36q5 4 10 0"
          fill="none"
          stroke="#27233d"
          strokeLinecap="round"
          strokeWidth="2"
        />
        <rect x="20" y="49" width="8" height="6" rx="3" fill={shade} />
        <rect x="36" y="49" width="8" height="6" rx="3" fill={shade} />
      </svg>
    </span>
  );
}
