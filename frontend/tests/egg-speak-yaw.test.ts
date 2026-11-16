import { describe, expect, it } from "vitest";
import {
  STAGE_FRONT_YAW,
  stageBodyYawTarget,
  stageSeatFacesFront,
} from "../components/stage3d/scholar-stage";
import { standingPlacement } from "../components/stage3d/placement";

describe("egg speaking body yaw", () => {
  it("keeps a front-facing seat still while speaking", () => {
    expect(stageSeatFacesFront(STAGE_FRONT_YAW)).toBe(true);
    expect(stageBodyYawTarget(STAGE_FRONT_YAW, true)).toBe(STAGE_FRONT_YAW);
    expect(stageBodyYawTarget(STAGE_FRONT_YAW, false)).toBe(STAGE_FRONT_YAW);
  });

  it("turns a side seat to front while speaking, then restores", () => {
    const side = standingPlacement("A").yaw;
    expect(stageSeatFacesFront(side)).toBe(false);
    expect(stageBodyYawTarget(side, true)).toBe(STAGE_FRONT_YAW);
    expect(stageBodyYawTarget(side, false)).toBe(side);
  });

  it("turns the near-camera seat when its rest yaw is not front", () => {
    const frontSeat = standingPlacement("E").yaw;
    expect(stageSeatFacesFront(frontSeat)).toBe(false);
    expect(stageBodyYawTarget(frontSeat, true)).toBe(STAGE_FRONT_YAW);
    expect(stageBodyYawTarget(frontSeat, false)).toBe(frontSeat);
  });
});
