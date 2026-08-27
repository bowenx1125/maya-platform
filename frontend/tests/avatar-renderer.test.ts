import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { applyAvatarConfigMaterials } from "../components/avatar/avatar-renderer";
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
});
