import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { findBone } from "../components/stage3d/scholar-stage";

function rig(names: string[]): THREE.Object3D {
  const root = new THREE.Object3D();
  for (const name of names) root.add(new THREE.Object3D());
  (root.children as THREE.Object3D[]).forEach((c, i) => {
    c.name = names[i];
  });
  return root;
}

describe("findBone rig-family aliases", () => {
  it("resolves UE-style elder bones (spine_02, neck_01)", () => {
    const root = rig([
      "Root",
      "Pelvis",
      "spine_01",
      "spine_02",
      "neck_01",
      "head",
    ]);
    expect(findBone(root, "head")?.name).toBe("head");
    expect(findBone(root, "neck")?.name).toBe("neck_01");
    expect(findBone(root, "torso")?.name).toBe("spine_02");
  });

  it("resolves AdvancedSkeleton noble bones (Chest_M, Neck_M)", () => {
    const root = rig(["Root_M", "Spine1_M", "Chest_M", "Neck_M", "Head_M"]);
    expect(findBone(root, "head")?.name).toBe("Head_M");
    expect(findBone(root, "neck")?.name).toBe("Neck_M");
    expect(findBone(root, "torso")?.name).toBe("Chest_M");
  });

  it("resolves Mixamo/RPM bones (Spine1/Spine2, Neck)", () => {
    const root = rig([
      "mixamorig:Hips",
      "mixamorig:Spine",
      "mixamorig:Spine1",
      "mixamorig:Spine2",
      "mixamorig:Neck",
      "mixamorig:Head",
    ]);
    expect(findBone(root, "head")?.name).toBe("mixamorig:Head");
    expect(findBone(root, "neck")?.name).toBe("mixamorig:Neck");
    expect(findBone(root, "torso")?.name).toBe("mixamorig:Spine2");
  });

  it("returns null when no bone matches", () => {
    const root = rig(["nothing", "here"]);
    expect(findBone(root, "head")).toBeNull();
    expect(findBone(root, "jaw")).toBeNull();
  });
});
