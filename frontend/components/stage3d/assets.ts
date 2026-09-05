/**
 * Local, licence-checked stage assets for Debates (beta).
 *
 * The base GLB carries the mesh, the skin and the idle clip. The other three
 * files carry nothing but an animation: the source exports were 11 MB each
 * because they repeated the same mesh and a 6 MB texture, so they were
 * re-packed to the animation samplers alone. Node names are preserved, which
 * is what lets a clip from one file drive the skeleton loaded from another.
 */

export const STAGE_ASSET_ROOT = "/avatars/laozi/";

export const STAGE_BASE_ASSET = `${STAGE_ASSET_ROOT}scholar_base.glb`;

/** Clip files keyed by the action name the stage plays them under. */
export const STAGE_CLIP_ASSETS = {
  sit: `${STAGE_ASSET_ROOT}clip_sit.glb`,
  talk: `${STAGE_ASSET_ROOT}clip_talk.glb`,
  wave: `${STAGE_ASSET_ROOT}clip_wave.glb`,
} as const;

export const STAGE_BACKDROP_ASSET = `${STAGE_ASSET_ROOT}sumie_bg.jpg`;

export type StageClipName = keyof typeof STAGE_CLIP_ASSETS;

/** Only paths under the stage asset root may reach the loader. */
export function isStageAssetUrl(value: string): boolean {
  return value.startsWith(STAGE_ASSET_ROOT) && !value.includes("..");
}
