import * as THREE from "three";
import { describe, expect, it } from "vitest";

import {
  applyRelaxedStandingPose,
  AVATAR_FITTED_HANG,
  AVATAR_ROBE_HANG,
  boneSide,
  findLimbBones,
  hangProfileForAsset,
  normalizeBoneName,
} from "../components/avatar/avatar-pose";

function bone(
  parent: THREE.Object3D | null,
  name: string,
  x: number,
  y: number,
  z: number,
): THREE.Bone {
  const joint = new THREE.Bone();
  joint.name = name;
  joint.position.set(x, y, z);
  parent?.add(joint);
  return joint;
}

function world(object: THREE.Object3D): THREE.Vector3 {
  return object.getWorldPosition(new THREE.Vector3());
}

describe("normalizeBoneName", () => {
  it("collapses mixamo prefixes and separator variants", () => {
    expect(normalizeBoneName("mixamorig:LeftArm")).toBe("leftarm");
    expect(normalizeBoneName("mixamorigLeftForeArm")).toBe("leftforearm");
    expect(normalizeBoneName("upperarm_l")).toBe("upperarml");
    expect(normalizeBoneName("LeftUpperArm")).toBe("leftupperarm");
    expect(normalizeBoneName("Shoulder_L")).toBe("shoulderl");
  });
});

describe("findLimbBones", () => {
  it("finds mixamo, RPM and scholar names and skips twist and part helpers", () => {
    const root = new THREE.Group();
    bone(root, "mixamorig:LeftArm", 0.2, 1.4, 0);
    bone(root, "mixamorig:LeftForeArm", 0.4, 1.4, 0);
    bone(root, "mixamorig:LeftHand", 0.7, 1.4, 0);
    bone(root, "upperarm_twist_01_l", 0.2, 1.4, 0);
    bone(root, "LeftShoulder", 0.05, 1.45, 0);
    bone(root, "upperarm_r", -0.2, 1.4, 0);
    bone(root, "lowerarm_r", -0.5, 1.4, 0);
    bone(root, "Hand_R", -0.7, 1.4, 0);
    bone(root, "lowerarm_twist_01_r", -0.5, 1.4, 0);

    expect(findLimbBones(root)).toEqual({
      left: {
        upperArm: "mixamorig:LeftArm",
        forearm: "mixamorig:LeftForeArm",
        hand: "mixamorig:LeftHand",
      },
      right: {
        upperArm: "upperarm_r",
        forearm: "lowerarm_r",
        hand: "Hand_R",
      },
    });
  });

  it("uses noble shoulder, elbow and wrist bones instead of their part helpers", () => {
    const root = new THREE.Group();
    const shoulder = bone(root, "Shoulder_L", 0.2, 1.4, 0);
    bone(shoulder, "ShoulderPart1_L", 0.1, 0, 0);
    const elbow = bone(shoulder, "Elbow_L", 0.3, 0, 0);
    bone(elbow, "ElbowPart1_L", 0.1, 0, 0);
    bone(elbow, "Wrist_L", 0.25, 0, 0);

    expect(findLimbBones(root).left).toEqual({
      upperArm: "Shoulder_L",
      forearm: "Elbow_L",
      hand: "Wrist_L",
    });
  });
});

describe("applyRelaxedStandingPose", () => {
  it("rotates a T-pose arm down from its bind pose and leaves the head alone", () => {
    const root = new THREE.Group();
    const upper = bone(root, "LeftArm", 0.12, 1.5, 0);
    const forearm = bone(upper, "LeftForeArm", 0.4, 0, 0);
    const hand = bone(forearm, "LeftHand", 0.3, 0, 0);
    bone(hand, "LeftHandMiddle1", 0.1, 0, 0);
    bone(hand, "LeftHandThumb1", 0.02, 0.01, 0.04);
    const head = bone(root, "Head", 0, 1.7, 0.02);
    const jaw = bone(head, "Bone_Jaw", 0, -0.05, 0.04);
    const headRest = head.quaternion.clone();
    const jawRest = jaw.quaternion.clone();
    const bind = upper.quaternion.clone();

    const pose = applyRelaxedStandingPose(root);
    const upperPos = world(upper);
    const forearmPos = world(forearm);
    const handPos = world(hand);

    expect(pose.left.upperArm).toBe("LeftArm");
    expect(forearmPos.y).toBeLessThan(upperPos.y - 0.2);
    expect(handPos.y).toBeLessThan(forearmPos.y - 0.1);
    expect(forearmPos.x).toBeGreaterThan(0);
    expect(handPos.z).toBeGreaterThan(upperPos.z);
    expect(upper.quaternion.angleTo(bind)).toBeGreaterThan(0.4);
    expect(head.quaternion.angleTo(headRest)).toBeLessThan(1e-6);
    expect(jaw.quaternion.angleTo(jawRest)).toBeLessThan(1e-6);
  });

  it("drops a right arm whose bind axes are mirrored", () => {
    const root = new THREE.Group();
    const upper = bone(root, "RightArm", -0.12, 1.5, 0);
    upper.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI);
    const forearm = bone(upper, "RightForeArm", 0.4, 0, 0);
    const hand = bone(forearm, "RightHand", 0.3, 0, 0);
    bone(hand, "RightHandMiddle1", 0.1, 0, 0);
    bone(hand, "RightHandThumb1", -0.02, 0.01, 0.04);
    const before = world(forearm);
    expect(before.x).toBeLessThan(world(upper).x);

    applyRelaxedStandingPose(root);
    const upperPos = world(upper);
    const forearmPos = world(forearm);
    const handPos = world(hand);

    expect(forearmPos.y).toBeLessThan(upperPos.y - 0.2);
    expect(handPos.y).toBeLessThan(forearmPos.y - 0.1);
    expect(forearmPos.x).toBeLessThan(0);
    expect(handPos.x).toBeLessThan(0);
    expect(handPos.z).toBeGreaterThan(upperPos.z);
  });

  it("swings an upper-arm twist sibling with the arm", () => {
    const root = new THREE.Group();
    const upper = bone(root, "UpperArm_L", 0.2, 1.5, 0);
    bone(upper, "lowerarm_l", 0.35, 0, 0);
    const twist = bone(root, "upperarm_twist_01_l", 0.2, 1.5, 0);
    const sleeve = bone(twist, "Bone_Sleeve_L04", 0.3, 0, 0);

    applyRelaxedStandingPose(root);

    expect(world(sleeve).y).toBeLessThan(world(twist).y - 0.15);
    expect(world(sleeve).x).toBeGreaterThan(0);
  });
});

describe("boneSide", () => {
  it("matches side tokens and leaves a trailing Roll unsided", () => {
    expect(boneSide("LeftArm")).toBe("left");
    expect(boneSide("upperarm_l")).toBe("left");
    expect(boneSide("Hand_R")).toBe("right");
    expect(boneSide("upperarm_twist_01_l")).toBe("left");
    expect(boneSide("upperarm_twist_Roll")).toBeNull();
    expect(boneSide("SomethingRoll")).toBeNull();
  });
});

describe("robe hang", () => {
  it("drops loose-robe arms less than a fitted body", () => {
    function posed(profile: typeof AVATAR_FITTED_HANG) {
      const root = new THREE.Group();
      const upper = bone(root, "LeftArm", 0.12, 1.5, 0);
      const forearm = bone(upper, "LeftForeArm", 0.45, 0, 0);
      bone(forearm, "LeftHand", 0.3, 0, 0);
      bone(forearm, "LeftHandMiddle1", 0.08, 0, 0);
      applyRelaxedStandingPose(root, profile);
      return world(upper).y - world(forearm).y;
    }

    const fittedDrop = posed(AVATAR_FITTED_HANG);
    const robeDrop = posed(AVATAR_ROBE_HANG);
    expect(robeDrop).toBeGreaterThan(0.05);
    expect(robeDrop).toBeLessThan(fittedDrop);
    expect(hangProfileForAsset("/avatars/elder-scholar.glb")).toBe(
      AVATAR_ROBE_HANG,
    );
    expect(hangProfileForAsset("/avatars/noble-scholar.glb")).toBe(
      AVATAR_ROBE_HANG,
    );
    expect(hangProfileForAsset("/avatars/female_1.glb")).toBe(
      AVATAR_FITTED_HANG,
    );
  });

  it("does not drag a Roll twist helper with the left arm", () => {
    const root = new THREE.Group();
    const upper = bone(root, "UpperArm_L", 0.2, 1.5, 0);
    bone(upper, "lowerarm_l", 0.35, 0, 0);
    const twist = bone(root, "upperarm_twist_Roll", 0.2, 1.5, 0);
    const sleeve = bone(twist, "Sleeve", 0.3, 0, 0);
    const before = world(sleeve);

    applyRelaxedStandingPose(root);

    const after = world(sleeve);
    expect(after.x).toBeCloseTo(before.x, 4);
    expect(after.y).toBeCloseTo(before.y, 4);
  });
});
