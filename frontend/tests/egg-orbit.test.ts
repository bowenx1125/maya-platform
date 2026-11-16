import { describe, expect, it } from "vitest";
import {
  eggOrbitYawAfterDrag,
  eggOrbitYawAfterInertia,
} from "../components/avatar/egg-orbit";

describe("egg preview orbit yaw", () => {
  it("spins yaw from horizontal drag without touching saved config", () => {
    const start = 0.25;
    const next = eggOrbitYawAfterDrag(start, 40);
    expect(next).toBeCloseTo(start - 40 * 0.01, 8);
    expect(eggOrbitYawAfterDrag(start, 0)).toBe(start);
  });

  it("decays inertia unless reduced motion asks for an immediate stop", () => {
    const spun = eggOrbitYawAfterInertia(1, 0.8, 0.05, false);
    expect(spun.yaw).toBeGreaterThan(1);
    expect(Math.abs(spun.velocity)).toBeLessThan(0.8);
    expect(eggOrbitYawAfterInertia(1, 0.8, 0.05, true)).toEqual({
      yaw: 1,
      velocity: 0,
    });
  });
});
