import type { components } from "../../lib/api/generated/schema";

export type AvatarConfig = components["schemas"]["AvatarConfig"];
/**
 * The frozen public catalog currently returns capabilities only.  Keep the
 * optional field here so a newer server can provide its own defaults without
 * changing the editor contract; the current server falls back to the exact
 * catalog defaults below.
 */
export type AvatarTemplate = components["schemas"]["AvatarTemplate"] & {
  default_config?: AvatarConfig;
};

export type AvatarState =
  "idle" | "listening" | "speaking" | "thinking" | "nod_yes";

export type AvatarExpression = AvatarConfig["default_expression"];
export type AvatarExpressionStrength = AvatarConfig["expression_strength"];
export type AvatarMotionStyle = AvatarConfig["motion_style"];

export const AVATAR_STATES: readonly AvatarState[] = [
  "idle",
  "listening",
  "speaking",
  "thinking",
  "nod_yes",
];

export const AVATAR_EXPRESSIONS: readonly AvatarExpression[] = [
  "neutral",
  "attentive",
  "happy",
  "serious_angry",
  "sad",
];

export const AVATAR_EXPRESSION_STRENGTHS: readonly AvatarExpressionStrength[] =
  ["low", "medium", "high"];

export const AVATAR_MOTION_STYLES: readonly AvatarMotionStyle[] = [
  "calm",
  "active",
];

export const AVATAR_MATERIAL_THEMES = [
  "demo",
  "warm_sand",
  "cool_slate",
  "civic_olive",
] as const;

export const AVATAR_EYE_COLORS = [
  "default",
  "brown",
  "hazel",
  "blue",
  "green",
  "gray",
] as const;

/**
 * Defaults mirror the server-owned M07 catalog.  The server response remains
 * authoritative for which IDs can be selected: these values are only used
 * after an available catalog entry has been returned, and unknown IDs fail
 * closed instead of receiving a fabricated configuration.
 */
export const AVATAR_TEMPLATE_DEFAULT_CONFIGS = {
  "wave1-default-head": {
    template_id: "wave1-default-head",
    material_theme: "demo",
    eye_color: null,
    default_expression: "neutral",
    expression_strength: "medium",
    motion_style: "calm",
  },
  "maya-warm-scholar": {
    template_id: "maya-warm-scholar",
    material_theme: "warm_sand",
    eye_color: "brown",
    default_expression: "attentive",
    expression_strength: "medium",
    motion_style: "calm",
  },
  "maya-civic-observer": {
    template_id: "maya-civic-observer",
    material_theme: "civic_olive",
    eye_color: "gray",
    default_expression: "serious_angry",
    expression_strength: "medium",
    motion_style: "active",
  },
} as const satisfies Readonly<Record<string, AvatarConfig>>;

export const CHAT_AVATAR_MODELS = {
  "wave1-default-head": {
    assetUrl: "/avatars/female_1.glb",
    labelKey: "chatAvatarModelClassic",
  },
  "maya-warm-scholar": {
    assetUrl: "/avatars/elder-scholar.glb",
    labelKey: "chatAvatarModelElderScholar",
  },
  "maya-civic-observer": {
    assetUrl: "/avatars/noble-scholar.glb",
    labelKey: "chatAvatarModelNobleScholar",
  },
} as const;

export type ChatAvatarModelId = keyof typeof CHAT_AVATAR_MODELS;

export function isChatAvatarModelId(value: string): value is ChatAvatarModelId {
  return Object.hasOwn(CHAT_AVATAR_MODELS, value);
}

function isAvatarConfigForTemplate(
  value: unknown,
  templateId: string,
): value is AvatarConfig {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate.template_id === templateId &&
    typeof candidate.material_theme === "string" &&
    (AVATAR_MATERIAL_THEMES as readonly string[]).includes(
      candidate.material_theme,
    ) &&
    (candidate.eye_color === null ||
      candidate.eye_color === undefined ||
      (typeof candidate.eye_color === "string" &&
        candidate.eye_color !== "default" &&
        (AVATAR_EYE_COLORS as readonly string[]).includes(
          candidate.eye_color,
        ))) &&
    typeof candidate.default_expression === "string" &&
    (AVATAR_EXPRESSIONS as readonly string[]).includes(
      candidate.default_expression,
    ) &&
    typeof candidate.expression_strength === "string" &&
    (AVATAR_EXPRESSION_STRENGTHS as readonly string[]).includes(
      candidate.expression_strength,
    ) &&
    typeof candidate.motion_style === "string" &&
    (AVATAR_MOTION_STYLES as readonly string[]).includes(candidate.motion_style)
  );
}

function completeAvatarConfig(value: AvatarConfig): AvatarConfig {
  return {
    template_id: value.template_id,
    material_theme: value.material_theme,
    eye_color: value.eye_color ?? null,
    default_expression: value.default_expression,
    expression_strength: value.expression_strength,
    motion_style: value.motion_style,
  };
}

/**
 * Resolve one complete, server-compatible config for a selected catalog row.
 * A server-provided default wins when present; malformed defaults and unknown
 * IDs are rejected rather than silently inventing values.
 */
export function avatarDefaultConfigForTemplate(
  template: Pick<AvatarTemplate, "id" | "available"> & {
    default_config?: unknown;
  },
): AvatarConfig | null {
  if (!template.available) return null;
  if (template.default_config !== undefined) {
    return isAvatarConfigForTemplate(template.default_config, template.id)
      ? completeAvatarConfig(template.default_config)
      : null;
  }
  const defaults = (
    AVATAR_TEMPLATE_DEFAULT_CONFIGS as Readonly<Record<string, AvatarConfig>>
  )[template.id];
  return defaults ? completeAvatarConfig(defaults) : null;
}

export const AVATAR_ASSET_URL = "/avatars/female_1.glb";
export const AVATAR_DECODER_PATH = "/avatars/draco/";

/**
 * Mirrors the server catalog asset registry. The public template DTO does not
 * carry a path, so full-body previews resolve the same GLB the catalog
 * registered for that template id.
 */
export const AVATAR_TEMPLATE_ASSETS = {
  "wave1-default-head": "/avatars/female_1.glb",
  "maya-warm-scholar": "/avatars/elder-scholar.glb",
  "maya-civic-observer": "/avatars/noble-scholar.glb",
} as const satisfies Readonly<Record<string, string>>;

export function avatarAssetUrlForTemplate(templateId: string): string {
  const registered = (
    AVATAR_TEMPLATE_ASSETS as Readonly<Record<string, string>>
  )[templateId];
  return registered ?? AVATAR_ASSET_URL;
}
