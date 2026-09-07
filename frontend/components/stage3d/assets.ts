/**
 * Stage assets for Debates (beta).
 *
 * One figure, shared by every speaker on the bench. It is the same asset the
 * platform's avatar preview already uses, chosen over a set of separately
 * animated bodies for one reason: those bodies carried a skeleton and no
 * blendshapes, so a speaking Agent could not open its mouth. This one carries
 * the full ARKit morph set, which is what lets a speech look like speech.
 */

export const STAGE_ASSET_ROOT = "/avatars/";

export const STAGE_BASE_ASSET = `${STAGE_ASSET_ROOT}female_1.glb`;

/** Draco decoder, served locally so the scene never reaches a CDN. */
export const STAGE_DECODER_PATH = `${STAGE_ASSET_ROOT}draco/`;

export const STAGE_BACKDROP_ASSET = `${STAGE_ASSET_ROOT}laozi/sumie_bg.jpg`;

/** Only paths under the stage asset root may reach the loader. */
export function isStageAssetUrl(value: string): boolean {
  return value.startsWith(STAGE_ASSET_ROOT) && !value.includes("..");
}
