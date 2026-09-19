import { describe, expect, it } from "vitest";

import {
  STAGE_SLOTS,
  standingPlacement,
} from "../components/stage3d/placement";

describe("roundtable standing placement", () => {
  it("puts two speakers opposite each other with both faces visible", () => {
    const left = standingPlacement("A");
    const right = standingPlacement("B");

    expect(left.x).toBeCloseTo(-right.x);
    expect(left.z).toBeCloseTo(right.z);
    expect(left.yaw).toBeCloseTo((Math.PI / 2) * 0.68);
    expect(right.yaw).toBeCloseTo((-Math.PI / 2) * 0.68);
  });

  it("reserves five stable world positions regardless of roster size", () => {
    const positions = STAGE_SLOTS.map((slot) => standingPlacement(slot));
    expect(
      new Set(positions.map(({ x, z }) => `${x.toFixed(3)}:${z.toFixed(3)}`))
        .size,
    ).toBe(5);
    expect(standingPlacement("C")).toEqual(standingPlacement("C"));
    expect(standingPlacement("E").x).toBe(0);
    expect(standingPlacement("E").z).toBeLessThan(standingPlacement("C").z);
  });
});
