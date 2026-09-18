/**
 * Stage assets for Debates (beta).
 *
 * Two purchased figures, shared by every speaker on the stage and cloned per
 * Agent so a five-Agent stage costs two downloads. Both figures have jaw
 * bones, which the stage animates for first-pass mouth movement.
 */

export const STAGE_ASSET_ROOT = "/avatars/";

/** Load order doubles as the deterministic variant order for stage slots. */
export const STAGE_CHARACTER_ASSETS = [
  `${STAGE_ASSET_ROOT}elder-scholar.glb`,
  `${STAGE_ASSET_ROOT}noble-scholar.glb`,
];

/** Draco decoder, served locally so the scene never reaches a CDN. */
export const STAGE_DECODER_PATH = `${STAGE_ASSET_ROOT}draco/`;

/** Only paths under the stage asset root may reach the loader. */
export function isStageAssetUrl(value: string): boolean {
  return value.startsWith(STAGE_ASSET_ROOT) && !value.includes("..");
}
