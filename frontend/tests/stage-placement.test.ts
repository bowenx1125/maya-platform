import { describe, expect, it } from "vitest";

import {
  stageCameraPositionBlocked,
  STAGE_SLOT_EXCLUSION_RADIUS,
  STAGE_SLOTS,
  STAGE_WALK_RADIUS,
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
    expect(standingPlacement("E").z).toBeGreaterThan(standingPlacement("C").z);
  });
});

describe("fixed-world stage camera collision", () => {
  const walkCenter = { x: 0, z: -5.4 };
  const centerZ = 1.15;
  const tableCollisionRadius = 1.63;

  it("keeps the walking camera inside the 2.5 metre courtyard envelope", () => {
    expect(
      stageCameraPositionBlocked(
        walkCenter,
        walkCenter,
        centerZ,
        tableCollisionRadius,
      ),
    ).toBe(false);
    expect(
      stageCameraPositionBlocked(
        { x: 0, z: walkCenter.z - STAGE_WALK_RADIUS },
        walkCenter,
        centerZ,
        tableCollisionRadius,
      ),
    ).toBe(false);
    expect(
      stageCameraPositionBlocked(
        { x: STAGE_WALK_RADIUS + 0.01, z: walkCenter.z },
        walkCenter,
        centerZ,
        tableCollisionRadius,
      ),
    ).toBe(true);
  });

  it("blocks the live table and all five reserved standing positions", () => {
    expect(
      stageCameraPositionBlocked(
        { x: 0, z: centerZ },
        walkCenter,
        centerZ,
        tableCollisionRadius,
      ),
    ).toBe(true);
    for (const slot of STAGE_SLOTS) {
      const position = standingPlacement(slot);
      expect(
        stageCameraPositionBlocked(
          { x: position.x, z: centerZ + position.z },
          { x: 0, z: centerZ },
          centerZ,
          1,
        ),
        `slot ${slot}`,
      ).toBe(true);
    }
    expect(STAGE_SLOT_EXCLUSION_RADIUS).toBe(0.8);
  });
});
