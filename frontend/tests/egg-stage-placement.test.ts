import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { describe, expect, it, vi } from "vitest";
import {
  EGG_CROWN_PAD,
  eggCrownWorldPosition,
  prepareEggModel,
} from "../components/stage3d/egg-model";
import { EGG_PROFILE as P } from "../components/stage3d/egg-profile";

const FLOOR_Y = -0.42;
const NORMALISED_HEIGHT = 1.7;

async function loadEgg() {
  const bytes = readFileSync(
    resolve(process.cwd(), "public/avatars/Maya-Egg.glb"),
  );
  const buffer = new ArrayBuffer(bytes.length);
  new Uint8Array(buffer).set(bytes);
  return new GLTFLoader()
    .register(() => ({
      name: "test_texture",
      loadTexture: async () => new THREE.Texture(),
    }))
    .parseAsync(buffer, "");
}

/** Mirror ScholarStage.groundCharacter's mesh-union lift against FLOOR_Y. */
function groundLikeStage(root: THREE.Object3D): void {
  root.updateWorldMatrix(true, true);
  const body = new THREE.Box3();
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh) || !object.visible) return;
    if (!object.geometry.boundingBox) object.geometry.computeBoundingBox();
    if (object.geometry.boundingBox) {
      body.union(
        object.geometry.boundingBox.clone().applyMatrix4(object.matrixWorld),
      );
    }
  });
  root.position.y += FLOOR_Y - body.min.y;
  root.updateWorldMatrix(true, true);
}

function worldMeshBounds(root: THREE.Object3D) {
  const body = new THREE.Box3();
  const parts: Record<string, { minY: number; maxY: number }> = {};
  root.updateWorldMatrix(true, true);
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh) || !object.visible) return;
    object.geometry.computeBoundingBox();
    const box = object.geometry
      .boundingBox!.clone()
      .applyMatrix4(object.matrixWorld);
    body.union(box);
    parts[object.name || "(unnamed)"] = {
      minY: box.min.y,
      maxY: box.max.y,
    };
  });
  return { body, parts };
}

describe("egg stage placement", () => {
  it("caches a remapped Shell bbox so grounding puts feet on the shared floor", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const gltf = await loadEgg();
    const egg = prepareEggModel(gltf.scene);
    egg.frame(0, false, true);
    const shell = egg.root.getObjectByName("Shell") as THREE.Mesh;
    // prepareEggModel must leave a fresh bbox — do not recompute before assert.
    expect(shell.geometry.boundingBox).not.toBeNull();
    expect(shell.geometry.boundingBox!.min.y).toBeCloseTo(P.bottom, 5);
    expect(shell.geometry.boundingBox!.max.y).toBeCloseTo(
      P.bottom + P.height,
      5,
    );

    egg.root.scale.setScalar(NORMALISED_HEIGHT / 2.7);
    egg.root.position.set(0, 0, 0);
    groundLikeStage(egg.root);
    const { body, parts } = worldMeshBounds(egg.root);
    expect(body.min.y).toBeCloseTo(FLOOR_Y, 3);
    expect(parts.Foot_L.minY).toBeCloseTo(FLOOR_Y, 3);
    expect(parts.Foot_R.minY).toBeCloseTo(FLOOR_Y, 3);
    expect(parts.Shell.minY).toBeGreaterThan(FLOOR_Y + 0.02);
    egg.dispose();
  }, 30_000);

  it("projects the overlay anchor from the Shell crown, not the root", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const gltf = await loadEgg();
    const egg = prepareEggModel(gltf.scene);
    egg.frame(0, false, true);
    egg.root.scale.setScalar(NORMALISED_HEIGHT / 2.7);
    egg.root.position.set(0, 0, 0);
    groundLikeStage(egg.root);

    const crown = eggCrownWorldPosition(egg.root, new THREE.Vector3());
    const root = new THREE.Vector3();
    egg.root.getWorldPosition(root);
    const shell = egg.root.getObjectByName("Shell") as THREE.Mesh;
    const tip = new THREE.Vector3(0, shell.geometry.boundingBox!.max.y, 0);
    shell.localToWorld(tip);

    expect(crown.y).toBeCloseTo(tip.y + EGG_CROWN_PAD, 5);
    expect(crown.y).toBeGreaterThan(root.y + 0.18 + 0.5);
    egg.dispose();
  }, 30_000);
});
