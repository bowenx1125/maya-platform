import { describe, expect, it } from "vitest";
import {
  EGG_FRONT_YAW,
  eggBodyYawTarget,
  eggSeatFacesFront,
} from "../components/stage3d/scholar-stage";
import { standingPlacement } from "../components/stage3d/placement";

describe("egg speaking body yaw", () => {
  it("keeps a front-facing seat still while speaking", () => {
    expect(eggSeatFacesFront(EGG_FRONT_YAW)).toBe(true);
    expect(eggBodyYawTarget(EGG_FRONT_YAW, true)).toBe(EGG_FRONT_YAW);
    expect(eggBodyYawTarget(EGG_FRONT_YAW, false)).toBe(EGG_FRONT_YAW);
  });

  it("turns a side seat to front while speaking, then restores", () => {
    const side = standingPlacement("A").yaw;
    expect(eggSeatFacesFront(side)).toBe(false);
    expect(eggBodyYawTarget(side, true)).toBe(EGG_FRONT_YAW);
    expect(eggBodyYawTarget(side, false)).toBe(side);
  });

  it("turns the near-camera seat when its rest yaw is not front", () => {
    const frontSeat = standingPlacement("E").yaw;
    expect(eggSeatFacesFront(frontSeat)).toBe(false);
    expect(eggBodyYawTarget(frontSeat, true)).toBe(EGG_FRONT_YAW);
    expect(eggBodyYawTarget(frontSeat, false)).toBe(frontSeat);
  });
});
