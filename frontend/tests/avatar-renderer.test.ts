import * as THREE from "three";
import { describe, expect, it, vi } from "vitest";

import {
  applyAvatarConfigMaterials,
  releaseAvatarWebGL,
} from "../components/avatar/avatar-renderer";
import type { AvatarConfig } from "../components/avatar/types";

const config: AvatarConfig = {
  template_id: "wave1-default-head",
  material_theme: "demo",
  eye_color: null,
  default_expression: "neutral",
  expression_strength: "medium",
  motion_style: "calm",
};

function triangleGeometry(): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(
      [-0.5, -0.5, 0, 0.5, -0.5, 0, 0, 0.5, 0],
      3,
    ),
  );
  return geometry;
}

describe("avatar webgl teardown", () => {
  it("does not force-lose a canvas the next viewer will reuse", () => {
    const dispose = vi.fn();
    const forceContextLoss = vi.fn();
    releaseAvatarWebGL({ dispose, forceContextLoss }, { isConnected: true });
    expect(dispose).toHaveBeenCalledTimes(1);
    expect(forceContextLoss).not.toHaveBeenCalled();
  });

  it("force-loses a canvas that has already left the document", () => {
    const dispose = vi.fn();
    const forceContextLoss = vi.fn();
    releaseAvatarWebGL({ dispose, forceContextLoss }, { isConnected: false });
    expect(dispose.mock.invocationCallOrder[0]).toBeLessThan(
      forceContextLoss.mock.invocationCallOrder[0],
    );
    expect(forceContextLoss).toHaveBeenCalledTimes(1);
  });
});

describe("avatar material shape", () => {
  it("keeps an ungrouped single-primitive mesh renderable after config", () => {
    const mesh = new THREE.Mesh(
      triangleGeometry(),
      new THREE.MeshStandardMaterial({ color: 0xffffff }),
    );
    mesh.name = "Wolf3D_Head";
    const root = new THREE.Group();
    root.add(mesh);

    applyAvatarConfigMaterials(root, config);

    // The shipped GLB uses this shape. An array material has no draw group
    // to dispatch, so Three.js would report ready while drawing no pixels.
    expect(mesh.geometry.groups).toHaveLength(0);
    expect(Array.isArray(mesh.material)).toBe(false);
    expect(mesh.material).toBeInstanceOf(THREE.Material);
    expect(mesh.material.userData.mayaAvatarMaterial).toBe(true);
  });

  it("preserves an existing multi-material array for grouped geometry", () => {
    const geometry = triangleGeometry();
    geometry.clearGroups();
    geometry.addGroup(0, 3, 0);
    geometry.addGroup(0, 3, 1);
    const mesh = new THREE.Mesh(geometry, [
      new THREE.MeshStandardMaterial({ color: 0xffffff }),
      new THREE.MeshStandardMaterial({ color: 0xffffff }),
    ]);
    mesh.name = "Wolf3D_Head";
    const root = new THREE.Group();
    root.add(mesh);

    applyAvatarConfigMaterials(root, config);

    expect(mesh.geometry.groups).toHaveLength(2);
    expect(Array.isArray(mesh.material)).toBe(true);
    expect(mesh.material).toHaveLength(2);
    expect(
      mesh.material.every((material) => material.userData.mayaAvatarMaterial),
    ).toBe(true);
  });

  it("gives two material themes different clothing and eye colors", () => {
    function painted(
      meshName: string,
      theme: AvatarConfig["material_theme"],
      eye: AvatarConfig["eye_color"],
    ): string {
      const mesh = new THREE.Mesh(
        triangleGeometry(),
        new THREE.MeshStandardMaterial({ color: 0xffffff }),
      );
      mesh.name = meshName;
      const root = new THREE.Group();
      root.add(mesh);
      applyAvatarConfigMaterials(root, {
        ...config,
        material_theme: theme,
        eye_color: eye,
      });
      const material = mesh.material as THREE.MeshStandardMaterial;
      expect(Array.isArray(mesh.material)).toBe(false);
      return material.color.getHexString();
    }

    const demoOutfit = painted("Wolf3D_Outfit_Top", "demo", null);
    const warmOutfit = painted("Wolf3D_Outfit_Top", "warm_sand", null);
    expect(demoOutfit).not.toBe(warmOutfit);
    expect(demoOutfit).not.toBe("ffffff");
    expect(warmOutfit).not.toBe("ffffff");

    const brownEye = painted("EyeLeft", "demo", "brown");
    const blueEye = painted("EyeLeft", "demo", "blue");
    expect(brownEye).not.toBe(blueEye);
  });
});
