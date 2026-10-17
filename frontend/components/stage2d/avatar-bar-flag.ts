/**
 * Beta gate for the 2D multi-avatar / Grok-motion bar as the debate stage.
 *
 * Precedence for the bar flag:
 * - URL explicit values win over env.
 * - Aliases: `avatarBar` and `grokBar` (same effect).
 * - Conflict: any explicit 0/false → off; else any explicit 1/true → on;
 *   else `NEXT_PUBLIC_DEBATE_AVATAR_BAR`.
 * Flag off → keep ScholarScene (prod 3D).
 * Experimental 3D while the bar is default: `stage3d=1` remounts ScholarScene.
 */
function parseSearch(
  search: string | URLSearchParams | null | undefined,
): URLSearchParams {
  if (search instanceof URLSearchParams) return search;
  if (typeof search === "string") {
    return new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  }
  if (typeof window !== "undefined") {
    return new URLSearchParams(window.location.search);
  }
  return new URLSearchParams();
}

function isTruthyFlag(value: string | null): boolean {
  return value === "1" || value === "true";
}

function isFalsyFlag(value: string | null): boolean {
  return value === "0" || value === "false";
}

export function isDebateAvatarBarEnabled(
  search: string | URLSearchParams | null | undefined = undefined,
  envValue: string | undefined = undefined,
): boolean {
  const params = parseSearch(search);

  const avatarBar = params.get("avatarBar");
  const grokBar = params.get("grokBar");

  // Explicit URL off wins (either alias).
  if (isFalsyFlag(avatarBar) || isFalsyFlag(grokBar)) return false;
  // Explicit URL on (either alias).
  if (isTruthyFlag(avatarBar) || isTruthyFlag(grokBar)) return true;

  const env =
    envValue ??
    (typeof process !== "undefined"
      ? process.env.NEXT_PUBLIC_DEBATE_AVATAR_BAR
      : undefined);
  return env === "1" || env === "true";
}

/** When avatar-bar is default, `stage3d=1` turns the experimental 3D bench back on. */
export function isExperimentalStage3dEnabled(
  search: string | URLSearchParams | null | undefined = undefined,
): boolean {
  const params = parseSearch(search);
  const value = params.get("stage3d");
  return isTruthyFlag(value);
}

export type DebateStageVisual = "avatar-bar" | "scholar3d";

/**
 * Resolve which stage visual to mount. Consumes only URL/env — never audio.
 */
export function resolveDebateStageVisual(
  search: string | URLSearchParams | null | undefined = undefined,
  envValue: string | undefined = undefined,
): DebateStageVisual {
  if (!isDebateAvatarBarEnabled(search, envValue)) return "scholar3d";
  if (isExperimentalStage3dEnabled(search)) return "scholar3d";
  return "avatar-bar";
}

export type ArenaIntensity = "low" | "med" | "high";

/**
 * Arena atmosphere intensity (Bomberman-style rhythm, not third-party art).
 * URL `?arenaIntensity=low|med|high`; default med. Invalid → med.
 */
export function resolveArenaIntensity(
  search: string | URLSearchParams | null | undefined = undefined,
  propValue: ArenaIntensity | string | null | undefined = undefined,
): ArenaIntensity {
  if (propValue === "low" || propValue === "med" || propValue === "high") {
    return propValue;
  }
  const params = parseSearch(search);
  const fromUrl = params.get("arenaIntensity");
  if (fromUrl === "low" || fromUrl === "med" || fromUrl === "high") {
    return fromUrl;
  }
  return "med";
}
