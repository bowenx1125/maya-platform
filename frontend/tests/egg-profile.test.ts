import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { describe, expect, it } from "vitest";
import {
  EGG_PROFILE as P,
  eggRadius,
  eggMouthBeat,
} from "../components/stage3d/egg-profile";
import { prepareEggModel } from "../components/stage3d/egg-model";

describe("C2 ovoid profile", () => {
  it("has the approved ratio, broad lower half and a rounded crown", () => {
    const radii = Array.from({ length: 1001 }, (_, i) => eggRadius(i / 1000));
    const widest = radii.indexOf(Math.max(...radii));
    expect((2 * radii[widest]) / P.height).toBeCloseTo(0.76, 3);
    expect(widest / 1000).toBeGreaterThanOrEqual(0.38);
    expect(widest / 1000).toBeLessThanOrEqual(0.42);
    expect(eggRadius(0.25)).toBeGreaterThan(eggRadius(0.75));
    expect(radii[0]).toBe(0);
    expect(radii[1000]).toBe(0);
    for (let i = 1; i <= widest; i++)
      expect(radii[i]).toBeGreaterThanOrEqual(radii[i - 1]);
    for (let i = widest + 1; i <= 1000; i++)
      expect(radii[i]).toBeLessThanOrEqual(radii[i - 1]);
    for (let i = 10; i < 990; i++)
      expect(Math.abs(radii[i + 1] - 2 * radii[i] + radii[i - 1])).toBeLessThan(
        0.001,
      );
    // At a rounded pole, radius grows as sqrt(distance), not as a pointed cone.
    expect(eggRadius(0.999) / eggRadius(0.996)).toBeCloseTo(0.5, 1);
    expect(P.mouthWidthRatio).toBeGreaterThanOrEqual(0.55);
    expect(P.mouthWidthRatio).toBeLessThanOrEqual(0.6);
  });
  it("keeps the exact fixed beat with smooth transitions", () => {
    for (const [t, w] of [
      [0, 0],
      [0.075, 1],
      [0.17, 1],
      [0.245, 0],
      [0.32, 0],
    ])
      expect(eggMouthBeat(t)).toBeCloseTo(w, 8);
    expect(eggMouthBeat(0.0375)).toBeCloseTo(0.5);
  });
  it("adapts the real GLB and closes within 120ms; reduced motion freezes the body", async () => {
    const bytes = readFileSync(
      resolve(process.cwd(), "public/avatars/Maya-Egg.glb"),
    );
    const buffer = new ArrayBuffer(bytes.length);
    new Uint8Array(buffer).set(bytes);
    const gltf = await new GLTFLoader()
      .register(() => ({
        name: "test_texture",
        loadTexture: async () => new THREE.Texture(),
      }))
      .parseAsync(buffer, "");
    const egg = prepareEggModel(gltf.scene);
    const shell = egg.root.getObjectByName("Shell") as THREE.Mesh;
    shell.geometry.computeBoundingBox();
    const size = shell.geometry.boundingBox!.getSize(new THREE.Vector3());
    expect(size.x / size.y).toBeGreaterThan(0.75);
    expect(size.x / size.y).toBeLessThan(0.8);
    egg.frame(1, true, true);
    egg.frame(1.1, true, true);
    expect(shell.scale.toArray()).toEqual([1, 1, 1]);
    expect(egg.root.rotation.z).toBe(0);
    const mouth = egg.root.children.at(-1) as THREE.Mesh;
    const open = Array.from(mouth.geometry.attributes.position.array);
    egg.frame(1.22, false, true);
    expect(Array.from(mouth.geometry.attributes.position.array)).not.toEqual(
      open,
    );
    const closed = Array.from(mouth.geometry.attributes.position.array);
    egg.frame(2, false, true);
    expect(Array.from(mouth.geometry.attributes.position.array)).toEqual(
      closed,
    );
  });
});
