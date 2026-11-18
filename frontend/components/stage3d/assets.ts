/**
 * Stage assets for Debates (beta) and the shared ScholarScene live classroom.
 *
 * The stage preloads every registered catalog mesh once, then clones the
 * mesh that matches each speaker's template_id. Seat index never selects
 * a figure. All paths stay under the local /avatars/ root.
 */

import { AVATAR_TEMPLATE_ASSETS } from "../avatar/types";

export const STAGE_ASSET_ROOT = "/avatars/";

/** Unique catalog GLBs the stage preloads; not a seat-variant order. */
export const STAGE_CHARACTER_ASSETS = Array.from(
  new Set(Object.values(AVATAR_TEMPLATE_ASSETS)),
);

/** Draco decoder, served locally so the scene never reaches a CDN. */
export const STAGE_DECODER_PATH = `${STAGE_ASSET_ROOT}draco/`;

/** Only paths under the stage asset root may reach the loader. */
export function isStageAssetUrl(value: string): boolean {
  return value.startsWith(STAGE_ASSET_ROOT) && !value.includes("..");
}
