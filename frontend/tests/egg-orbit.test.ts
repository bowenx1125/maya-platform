import { describe, expect, it } from "vitest";
import { OrthographicCamera, Vector3 } from "three";
import {
  eggOrbitYawAfterDrag,
  eggOrbitYawAfterInertia,
} from "../components/avatar/egg-orbit";

describe("egg preview orbit yaw", () => {
  it("spins yaw from horizontal drag without touching saved config", () => {
    const start = 0.25;
    const next = eggOrbitYawAfterDrag(start, 40);
    expect(next).toBeCloseTo(start + 40 * 0.01, 8);
    expect(eggOrbitYawAfterDrag(start, 0)).toBe(start);
  });

  it.each([-40, 40])(
    "moves the face on screen with a %s pixel drag and continues that direction on release",
    (dx) => {
      const camera = new OrthographicCamera(-1.72, 1.72, 1.72, -1.72, 0.1, 30);
      camera.position.set(0, 1.35, 9);
      camera.lookAt(0, 1.35, 0);
      camera.updateMatrixWorld();
      const face = new Vector3(0, 1.35, 1);
      const screenX = (yaw: number) =>
        face
          .clone()
          .applyAxisAngle(new Vector3(0, 1, 0), yaw)
          .project(camera).x;
      const yaw = eggOrbitYawAfterDrag(0, dx);
      expect(Math.sign(screenX(yaw) - screenX(0))).toBe(Math.sign(dx));
      const velocity = (yaw - 0) / 0.1;
      const released = eggOrbitYawAfterInertia(yaw, velocity, 0.05, false);
      expect(Math.sign(screenX(released.yaw) - screenX(yaw))).toBe(Math.sign(dx));
    },
  );

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
