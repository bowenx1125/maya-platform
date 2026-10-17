/**
 * Beta gate for the 2D multi-avatar bar as the default debate stage.
 *
 * Precedence: URL `avatarBar=1` wins when present; otherwise
 * `NEXT_PUBLIC_DEBATE_AVATAR_BAR=1`. Flag off → keep ScholarScene (prod 3D).
 * Experimental 3D while the bar is default: `stage3d=1` remounts ScholarScene.
 */
export function isDebateAvatarBarEnabled(
  search: string | URLSearchParams | null | undefined = undefined,
  envValue: string | undefined = undefined,
): boolean {
  const params =
    search instanceof URLSearchParams
      ? search
      : typeof search === "string"
        ? new URLSearchParams(
            search.startsWith("?") ? search.slice(1) : search,
          )
        : typeof window !== "undefined"
          ? new URLSearchParams(window.location.search)
          : new URLSearchParams();

  const fromUrl = params.get("avatarBar");
  if (fromUrl === "1" || fromUrl === "true") return true;
  if (fromUrl === "0" || fromUrl === "false") return false;

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
  const params =
    search instanceof URLSearchParams
      ? search
      : typeof search === "string"
        ? new URLSearchParams(
            search.startsWith("?") ? search.slice(1) : search,
          )
        : typeof window !== "undefined"
          ? new URLSearchParams(window.location.search)
          : new URLSearchParams();
  const value = params.get("stage3d");
  return value === "1" || value === "true";
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
