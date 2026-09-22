export const STAGE_SLOTS = ["A", "B", "C", "D", "E"] as const;
export type StageSlot = (typeof STAGE_SLOTS)[number];

export const STAGE_STANDING_RADIUS = 1.6;
export const STAGE_WALK_RADIUS = 2.5;
export const STAGE_SLOT_EXCLUSION_RADIUS = 0.8;

const FIXED_STANDING_POSITIONS: Record<StageSlot, { x: number; z: number }> = {
  A: { x: -1.6, z: 0 },
  B: { x: 1.6, z: 0 },
  C: { x: -1.05, z: -1.18 },
  D: { x: 1.05, z: -1.18 },
  E: { x: 0, z: 1.48 },
};

export function standingPlacement(slot: StageSlot) {
  const { x, z } = FIXED_STANDING_POSITIONS[slot];
  const towardTable = Math.atan2(-x, -z);
  return { x, z, yaw: towardTable * 0.68 };
}

export type StagePoint = { x: number; z: number };

/** Camera collision for the fixed metric stage; occupied and empty slots agree. */
export function stageCameraPositionBlocked(
  point: StagePoint,
  walkCenter: StagePoint,
  stageCenterZ: number,
  tableCollisionRadius: number,
): boolean {
  if (
    Math.hypot(point.x - walkCenter.x, point.z - walkCenter.z) >
    STAGE_WALK_RADIUS + Number.EPSILON * 8
  ) {
    return true;
  }
  if (Math.hypot(point.x, point.z - stageCenterZ) < tableCollisionRadius) {
    return true;
  }
  return STAGE_SLOTS.some((slot) => {
    const position = standingPlacement(slot);
    return (
      Math.hypot(point.x - position.x, point.z - (stageCenterZ + position.z)) <
      STAGE_SLOT_EXCLUSION_RADIUS
    );
  });
}
