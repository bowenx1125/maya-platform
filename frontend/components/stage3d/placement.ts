export const STAGE_SLOTS = ["A", "B", "C", "D", "E"] as const;
export type StageSlot = (typeof STAGE_SLOTS)[number];
export type StageCameraStop = "overview" | StageSlot;

export const STAGE_STANDING_RADIUS = 1.6;

const FIXED_STANDING_POSITIONS: Record<StageSlot, { x: number; z: number }> = {
  A: { x: -1.6, z: 0 },
  B: { x: 1.6, z: 0 },
  C: { x: -1.18, z: -1.02 },
  D: { x: 1.18, z: -1.02 },
  E: { x: 0, z: -1.48 },
};

const CAMERA_SLOT_ROUTE: readonly StageSlot[] = ["A", "C", "E", "D", "B"];

export function stageCameraRoute(
  occupiedSlots: readonly StageSlot[],
): StageCameraStop[] {
  const occupied = new Set(occupiedSlots);
  return [
    "overview",
    ...CAMERA_SLOT_ROUTE.filter((slot) => occupied.has(slot)),
  ];
}

export function standingPlacement(slot: StageSlot) {
  const { x, z } = FIXED_STANDING_POSITIONS[slot];
  const towardTable = Math.atan2(-x, -z);
  return { x, z, yaw: towardTable * 0.68 };
}
