import { describe, expect, it } from "vitest";

import { standingPlacement } from "../components/stage3d/placement";

describe("roundtable standing placement", () => {
  it("puts two speakers on opposite sides, looking directly at each other", () => {
    const left = standingPlacement(0, 2);
    const right = standingPlacement(1, 2);

    expect(left.x).toBeCloseTo(-right.x);
    expect(left.z).toBeCloseTo(right.z);
    expect(left.yaw).toBeCloseTo(Math.PI / 2);
    expect(right.yaw).toBeCloseTo(-Math.PI / 2);
  });

  it.each([3, 4, 5])("spaces %i speakers evenly around the table", (count) => {
    const positions = Array.from({ length: count }, (_, index) =>
      standingPlacement(index, count),
    );
    const centerX = positions.reduce((sum, position) => sum + position.x, 0);
    const centerZ = positions.reduce((sum, position) => sum + position.z, 0);

    expect(centerX).toBeCloseTo(0);
    expect(centerZ).toBeCloseTo(0);
    expect(
      new Set(positions.map(({ x, z }) => `${x.toFixed(3)}:${z.toFixed(3)}`))
        .size,
    ).toBe(count);
  });
});
