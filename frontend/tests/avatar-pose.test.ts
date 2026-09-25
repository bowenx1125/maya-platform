import * as THREE from "three";
import { describe, expect, it } from "vitest";

import {
  applyIdleBreath,
  applyRelaxedStandingPose,
  findLimbBones,
  idleBreathAngle,
  normalizeBoneName,
  selectIdleClip,
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

  it("breathes from the spine rest pose without drifting", () => {
    const root = new THREE.Group();
    const spine = bone(root, "Spine2", 0, 1.3, 0);
    bone(spine, "Neck", 0, 0.2, 0);
    const pose = applyRelaxedStandingPose(root);
    expect(pose.breathBoneName).toBe("Spine2");
    const rest = spine.quaternion.clone();

    applyIdleBreath(pose, root, 0);
    expect(spine.quaternion.angleTo(rest)).toBeLessThan(1e-6);

    const peak = Math.PI / (2 * 1.4);
    expect(Math.abs(idleBreathAngle(peak))).toBeGreaterThan(0.01);
    applyIdleBreath(pose, root, peak);
    const bent = spine.quaternion.angleTo(rest);
    expect(bent).toBeGreaterThan(0.005);
    expect(bent).toBeLessThan(0.03);

    applyIdleBreath(pose, root, 0);
    expect(spine.quaternion.angleTo(rest)).toBeLessThan(1e-6);
  });
});

describe("selectIdleClip", () => {
  it("plays a named idle clip and refuses bind poses", () => {
    expect(selectIdleClip([{ name: "Walk" }, { name: "Idle" }])?.name).toBe(
      "Idle",
    );
    expect(selectIdleClip([{ name: "breathing_stand" }])?.name).toBe(
      "breathing_stand",
    );
    expect(selectIdleClip([{ name: "TPose" }])).toBeNull();
    expect(selectIdleClip([{ name: "A-Pose" }, { name: "Bind" }])).toBeNull();
    expect(selectIdleClip([])).toBeNull();
  });
});
