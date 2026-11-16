import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { describe, expect, it, vi } from "vitest";
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
    const canvasContext = vi
      .spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(null);
    const egg = prepareEggModel(gltf.scene);
    const shell = egg.root.getObjectByName("Shell") as THREE.Mesh;
    shell.geometry.computeBoundingBox();
    const size = shell.geometry.boundingBox!.getSize(new THREE.Vector3());
    expect(size.x / size.y).toBeGreaterThan(0.75);
    expect(size.x / size.y).toBeLessThan(0.8);
    const positions = shell.geometry.attributes.position;
    for (let i = 0; i < positions.count; i += 32) {
      const h = (positions.getY(i) - P.bottom) / P.height;
      if (h > 0.01 && h < 0.99)
        expect(Math.hypot(positions.getX(i), positions.getZ(i))).toBeCloseTo(
          eggRadius(h),
          5,
        );
    }
    for (const [suffix, sign] of [
      ["L", -1],
      ["R", 1],
    ] as const) {
      const foot = egg.root.getObjectByName(`Foot_${suffix}`)!;
      const join = egg.root.getObjectByName(`Fillet_Foot_${suffix}`)!;
      expect(foot.position.toArray()).toEqual([sign * P.footX, 0.255, 0.17]);
      expect(join.position.toArray()).toEqual([sign * P.footX, 0.355, 0.105]);
      expect(join.scale.toArray()).toEqual([0.092, 0.095, 0.13]);
    }
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

    const shader = {
      uniforms: {} as Record<string, { value: unknown }>,
      vertexShader:
        "#include <common>\n#include <begin_vertex>\n#include <worldpos_vertex>",
      fragmentShader:
        "#include <common>\n#include <color_fragment>\n#include <lights_physical_pars_fragment>\n#include <opaque_fragment>",
    };
    const shellMaterial = shell.material as THREE.MeshPhysicalMaterial;
    shellMaterial.onBeforeCompile(
      shader as Parameters<THREE.Material["onBeforeCompile"]>[0],
      {} as THREE.WebGLRenderer,
    );
    expect(shader.vertexShader).toContain("vEggLocal = position");
    expect(shader.fragmentShader).toContain("if(vEggLocal.z > 0.0)");
    expect(shader.fragmentShader).toContain("texture2D(eggInk, uv)");
    const texture = shader.uniforms.eggInk.value as THREE.Texture;
    expect(texture.colorSpace).toBe(THREE.SRGBColorSpace);
    for (const name of [
      "Hand_L",
      "Hand_R",
      "Foot_L",
      "Foot_R",
      "Fillet_Hand_L",
    ]) {
      const limb = egg.root.getObjectByName(name) as THREE.Mesh;
      expect(limb.material).not.toBe(shell.material);
      expect(
        (limb.material as THREE.Material).customProgramCacheKey(),
      ).not.toContain("drawing");
    }
    const version = texture.version;
    egg.setDrawing({
      version: 1,
      strokes: [
        {
          id: "ink",
          color: "#8C4B9E",
          width: 0.02,
          opacity: 1,
          points: [{ x: 0.5, y: 0.2 }],
        },
      ],
      mouth: { x: 0.55, y: 0.5 },
    });
    expect(texture.version).toBeGreaterThan(version);
    egg.frame(3, false, true);
    expect(mouth.geometry.attributes.position.getX(64)).toBeCloseTo(
      0.05 * P.height * P.widthRatio,
      5,
    );
    expect(mouth.geometry.attributes.position.getY(64)).toBeCloseTo(
      P.bottom + P.height * 0.5,
      5,
    );
    const dispose = vi.spyOn(texture, "dispose");
    egg.dispose();
    expect(dispose).toHaveBeenCalledOnce();
    canvasContext.mockRestore();
  });
});
