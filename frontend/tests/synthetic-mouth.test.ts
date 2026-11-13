import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { selectMouthRegion } from "@/components/stage3d/synthetic-mouth";

function positionsAlongAxis(
  axis: THREE.Vector3,
  headPos: THREE.Vector3,
  spans: number[],
): THREE.Vector3[] {
  return spans.map((t) => headPos.clone().addScaledVector(axis, t));
}

describe("selectMouthRegion", () => {
  const headPos = new THREE.Vector3(0, 1.6, 0);
  const axis = new THREE.Vector3(0, 1, 0);

  it("selects only head-weighted vertices below the region top", () => {
    // Four vertices along the skull axis at t = -0.02, 0.1, 0.2, 0.5 of the span.
    const span = 0.2;
    const spans = [-0.004, 0.02, 0.04, 0.1];
    const positions = positionsAlongAxis(axis, headPos, spans);
    const weights = [1, 1, 0.1, 1];
    const region = selectMouthRegion(positions, weights, headPos, axis, span);
    const indices = region.map((r) => r.index);
    expect(indices).toContain(0);
    expect(indices).toContain(1);
    expect(indices).not.toContain(2); // low head weight
    expect(indices).not.toContain(3); // above REGION_TOP
  });

  it("weights the chin heavier than the mouth line", () => {
    const span = 0.2;
    const spans = [0.0, 0.07];
    const positions = positionsAlongAxis(axis, headPos, spans);
    const weights = [1, 1];
    const region = selectMouthRegion(positions, weights, headPos, axis, span);
    const [chin, mouthLine] = region;
    expect(chin.weight).toBeGreaterThan(mouthLine.weight);
  });

  it("returns nothing for a degenerate skull span", () => {
    const positions = positionsAlongAxis(axis, headPos, [0.02, 0.04]);
    const region = selectMouthRegion(positions, [1, 1], headPos, axis, 0);
    expect(region).toHaveLength(0);
  });
});
