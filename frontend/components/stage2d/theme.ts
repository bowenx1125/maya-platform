import type { AvatarConfig } from "../avatar";

/** Skin fill per platform material theme (mirrors stage3d scholar-stage). */
export const AVATAR_BAR_SKIN: Record<AvatarConfig["material_theme"], string> = {
  demo: "#d5a27c",
  warm_sand: "#c88b68",
  cool_slate: "#a9b9c9",
  civic_olive: "#a49a75",
};

/** High-saturation accent ring / glow per theme (arena “bomberman” pop). */
export const AVATAR_BAR_ACCENT: Record<AvatarConfig["material_theme"], string> =
  {
    demo: "#5b8cff",
    warm_sand: "#ff7a3d",
    cool_slate: "#3fd0ff",
    civic_olive: "#b6e34a",
  };

export function avatarBarSkin(
  theme: AvatarConfig["material_theme"] | string | undefined,
): string {
  return (
    AVATAR_BAR_SKIN[theme as AvatarConfig["material_theme"]] ??
    AVATAR_BAR_SKIN.demo
  );
}

export function avatarBarAccent(
  theme: AvatarConfig["material_theme"] | string | undefined,
): string {
  return (
    AVATAR_BAR_ACCENT[theme as AvatarConfig["material_theme"]] ??
    AVATAR_BAR_ACCENT.demo
  );
}
