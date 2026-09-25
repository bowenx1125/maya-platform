import * as THREE from "three";

export type AvatarPoseSide = "left" | "right";

export type AvatarLimbMatch = {
  upperArm: string | null;
  forearm: string | null;
  hand: string | null;
};

export type AvatarLimbSet = Record<AvatarPoseSide, AvatarLimbMatch>;

export type AvatarRestPose = {
  left: AvatarLimbMatch;
  right: AvatarLimbMatch;
  breathBoneName: string | null;
  breathBone: THREE.Object3D | null;
  breathRest: THREE.Quaternion | null;
};

/**
 * Registered figures face root-local +Z with +Y up. These are hang directions
 * in that frame: mostly down, a little out, and a forearm that sits forward of
 * the upper arm so the elbow is slightly bent.
 */
const HANG = {
  upperArm: { lateral: 0.18, down: 0.97, forward: 0.16 },
  forearm: { lateral: 0.05, down: 0.84, forward: 0.52 },
  hand: { lateral: 0.03, down: 0.93, forward: 0.28 },
} as const;

const PALM_BACK = 0.35;
const MAX_PALM_TWIST = THREE.MathUtils.degToRad(50);

/** One breath cycle is slow enough to read as breathing, not a nod. */
export const AVATAR_IDLE_BREATH_SPEED = 1.4;
export const AVATAR_IDLE_BREATH_RADIANS = 0.012;

const UPPER_ARM: Record<AvatarPoseSide, readonly string[]> = {
  left: [
    "leftarm",
    "leftupperarm",
    "upperarml",
    "upperarmleft",
    "lupperarm",
    "arml",
    "armleft",
    "shoulderl",
  ],
  right: [
    "rightarm",
    "rightupperarm",
    "upperarmr",
    "upperarmright",
    "rupperarm",
    "armr",
    "armright",
    "shoulderr",
  ],
};

const FOREARM: Record<AvatarPoseSide, readonly string[]> = {
  left: [
    "leftforearm",
    "forearml",
    "forearmleft",
    "lforearm",
    "lowerarml",
    "lowerarmleft",
    "llowerarm",
    "elbowl",
    "leftelbow",
  ],
  right: [
    "rightforearm",
    "forearmr",
    "forearmright",
    "rforearm",
    "lowerarmr",
    "lowerarmright",
    "rlowerarm",
    "elbowr",
    "rightelbow",
  ],
};

const HAND: Record<AvatarPoseSide, readonly string[]> = {
  left: [
    "lefthand",
    "handl",
    "handleft",
    "lhand",
    "wristl",
    "leftwrist",
    "lwrist",
  ],
  right: [
    "righthand",
    "handr",
    "handright",
    "rhand",
    "wristr",
    "rightwrist",
    "rwrist",
  ],
};

const BREATH_BONES = [
  "chestm",
  "chest",
  "spine2",
  "spine02",
  "spine1",
  "spine01",
  "spine",
] as const;

const IDLE_CLIP = /idle|stand(?:ing)?|rest|breath|relax/i;
const BIND_CLIP = /t[-_ ]?pose|a[-_ ]?pose|\bbind\b/i;

/**
 * Strip Mixamo prefixes and separators so `mixamorig:LeftArm`, `LeftUpperArm`
 * and `upperarm_l` compare as the same kind of token.
 */
export function normalizeBoneName(name: string): string {
  return name
    .toLowerCase()
    .replace(/^mixamorig[:_-]*/, "")
    .replace(/[^a-z0-9]/g, "");
}

function isHelperBone(name: string): boolean {
  return /twist|part\d|(?:^|_)(?:ik|fk)(?:_|$)|^ik|^fk/i.test(name);
}

function indexBones(root: THREE.Object3D): Map<string, THREE.Object3D> {
  const bones = new Map<string, THREE.Object3D>();
  root.traverse((object) => {
    if (!object.name || isHelperBone(object.name)) return;
    const key = normalizeBoneName(object.name);
    if (!bones.has(key)) bones.set(key, object);
  });
  return bones;
}

function pickBone(
  bones: Map<string, THREE.Object3D>,
  names: readonly string[],
): THREE.Object3D | null {
  for (const name of names) {
    const found = bones.get(name);
    if (found) return found;
  }
  return null;
}

function matchLimb(
  bones: Map<string, THREE.Object3D>,
  side: AvatarPoseSide,
): {
  match: AvatarLimbMatch;
  upper: THREE.Object3D | null;
  forearm: THREE.Object3D | null;
  hand: THREE.Object3D | null;
} {
  const upper = pickBone(bones, UPPER_ARM[side]);
  const forearm = pickBone(bones, FOREARM[side]);
  const hand = pickBone(bones, HAND[side]);
  return {
    match: {
      upperArm: upper?.name ?? null,
      forearm: forearm?.name ?? null,
      hand: hand?.name ?? null,
    },
    upper,
    forearm,
    hand,
  };
}

export function findLimbBones(root: THREE.Object3D): AvatarLimbSet {
  const bones = indexBones(root);
  return {
    left: matchLimb(bones, "left").match,
    right: matchLimb(bones, "right").match,
  };
}

function boneSide(name: string): AvatarPoseSide | null {
  const normalized = normalizeBoneName(name);
  if (normalized.includes("left") || normalized.endsWith("l")) return "left";
  if (normalized.includes("right") || normalized.endsWith("r")) return "right";
  return null;
}

function isDescendantOf(
  object: THREE.Object3D,
  ancestor: THREE.Object3D,
): boolean {
  let parent = object.parent;
  while (parent) {
    if (parent === ancestor) return true;
    parent = parent.parent;
  }
  return false;
}

function hasDescendant(
  ancestor: THREE.Object3D,
  candidate: THREE.Object3D,
): boolean {
  return candidate === ancestor || isDescendantOf(candidate, ancestor);
}

function twistCompanions(
  root: THREE.Object3D,
  primary: THREE.Object3D,
  segment: "upper" | "fore",
  side: AvatarPoseSide,
): THREE.Object3D[] {
  const segmentPattern =
    segment === "upper" ? /upperarm|uparm/i : /lowerarm|forearm/i;
  const found: THREE.Object3D[] = [];
  root.traverse((object) => {
    if (object === primary || !object.name) return;
    if (!/twist/i.test(object.name)) return;
    if (!segmentPattern.test(object.name)) return;
    if (boneSide(object.name) !== side) return;
    if (isDescendantOf(object, primary)) return;
    found.push(object);
  });
  return found;
}

function applyWorldDelta(
  bone: THREE.Object3D,
  worldDelta: THREE.Quaternion,
): void {
  const parentWorld = bone.parent
    ? bone.parent.getWorldQuaternion(new THREE.Quaternion())
    : new THREE.Quaternion();
  const localDelta = parentWorld
    .clone()
    .invert()
    .multiply(worldDelta)
    .multiply(parentWorld);
  bone.quaternion.premultiply(localDelta);
}

function hangDirection(
  root: THREE.Object3D,
  lateral: number,
  weights: { lateral: number; down: number; forward: number },
): THREE.Vector3 {
  return new THREE.Vector3(
    lateral * weights.lateral,
    -weights.down,
    weights.forward,
  )
    .normalize()
    .transformDirection(root.matrixWorld);
}

/**
 * Swing `bone` so the vector toward `child` matches `desiredWorldDirection`.
 * The delta is the shortest rotation from the current bind direction, so a
 * rig whose local axes are mirrored still hangs on the correct side.
 */
function swingChildToward(
  bone: THREE.Object3D,
  child: THREE.Object3D,
  desiredWorldDirection: THREE.Vector3,
): THREE.Quaternion | null {
  const origin = bone.getWorldPosition(new THREE.Vector3());
  const current = child.getWorldPosition(new THREE.Vector3()).sub(origin);
  if (current.lengthSq() < 1e-8 || desiredWorldDirection.lengthSq() < 1e-8) {
    return null;
  }
  const worldDelta = new THREE.Quaternion().setFromUnitVectors(
    current.normalize(),
    desiredWorldDirection.clone().normalize(),
  );
  applyWorldDelta(bone, worldDelta);
  return worldDelta;
}

function primaryDigit(hand: THREE.Object3D): THREE.Object3D | null {
  let best: THREE.Object3D | null = null;
  let bestScore = -1;
  hand.traverse((object) => {
    if (object === hand || !object.name) return;
    if (!/middle|index/i.test(object.name) || /twist/i.test(object.name))
      return;
    let score = /middle/i.test(object.name) ? 10 : 4;
    if (/(?:^|[^0-9])0?1(?:[^0-9]|$)/.test(object.name)) score += 3;
    if (/(?:^|[^0-9])[234](?:[^0-9]|$)/.test(object.name)) score -= 5;
    if (score > bestScore) {
      best = object;
      bestScore = score;
    }
  });
  return best;
}

function proximalThumb(hand: THREE.Object3D): THREE.Object3D | null {
  let best: THREE.Object3D | null = null;
  hand.traverse((object) => {
    if (best || object === hand || !object.name) return;
    if (!/thumb/i.test(object.name)) return;
    if (/(?:^|[^0-9])0?1(?:[^0-9]|$)/.test(object.name)) best = object;
  });
  return best;
}

function relaxPalm(
  root: THREE.Object3D,
  hand: THREE.Object3D,
  digit: THREE.Object3D,
  lateral: number,
): void {
  const thumb = proximalThumb(hand);
  if (!thumb) return;
  const origin = hand.getWorldPosition(new THREE.Vector3());
  const toDigit = digit.getWorldPosition(new THREE.Vector3()).sub(origin);
  const toThumb = thumb.getWorldPosition(new THREE.Vector3()).sub(origin);
  if (toDigit.lengthSq() < 1e-8 || toThumb.lengthSq() < 1e-8) return;
  const axis = toDigit.clone().normalize();
  // Mirrored right-hand rigs flip the cross product, so the same order points
  // out of the back of the hand. Negate that side before twisting the palm in.
  const palm = new THREE.Vector3().crossVectors(toDigit, toThumb).normalize();
  if (lateral < 0) palm.negate();
  const desired = new THREE.Vector3(-lateral, 0, -PALM_BACK)
    .normalize()
    .transformDirection(root.matrixWorld);
  const currentFlat = palm.clone().projectOnPlane(axis);
  const desiredFlat = desired.clone().projectOnPlane(axis);
  if (currentFlat.lengthSq() < 1e-8 || desiredFlat.lengthSq() < 1e-8) return;
  currentFlat.normalize();
  desiredFlat.normalize();
  if (currentFlat.angleTo(desiredFlat) > MAX_PALM_TWIST) return;
  const worldDelta = new THREE.Quaternion().setFromUnitVectors(
    currentFlat,
    desiredFlat,
  );
  applyWorldDelta(hand, worldDelta);
}

function poseSide(
  root: THREE.Object3D,
  side: AvatarPoseSide,
  upper: THREE.Object3D | null,
  forearm: THREE.Object3D | null,
  hand: THREE.Object3D | null,
): void {
  if (!upper) return;
  root.updateMatrixWorld(true);
  const local = root.worldToLocal(upper.getWorldPosition(new THREE.Vector3()));
  const lateral = Math.sign(local.x) || (side === "left" ? 1 : -1);
  const upperEnd = forearm && hasDescendant(upper, forearm) ? forearm : hand;
  if (upperEnd && upperEnd !== upper) {
    const delta = swingChildToward(
      upper,
      upperEnd,
      hangDirection(root, lateral, HANG.upperArm),
    );
    if (delta) {
      for (const twist of twistCompanions(root, upper, "upper", side)) {
        applyWorldDelta(twist, delta);
      }
    }
  }
  root.updateMatrixWorld(true);
  if (forearm && hand && hasDescendant(forearm, hand)) {
    const delta = swingChildToward(
      forearm,
      hand,
      hangDirection(root, lateral, HANG.forearm),
    );
    if (delta) {
      for (const twist of twistCompanions(root, forearm, "fore", side)) {
        applyWorldDelta(twist, delta);
      }
    }
  }
  root.updateMatrixWorld(true);
  if (!hand) return;
  const digit = primaryDigit(hand);
  if (digit) {
    swingChildToward(hand, digit, hangDirection(root, lateral, HANG.hand));
    root.updateMatrixWorld(true);
    relaxPalm(root, hand, digit, lateral);
  }
}

function findBreathBone(
  bones: Map<string, THREE.Object3D>,
): THREE.Object3D | null {
  for (const name of BREATH_BONES) {
    const found = bones.get(name);
    if (found) return found;
  }
  return null;
}

/**
 * Hang both arms from the bind pose. Feet, head, jaw and face bones are left
 * alone. Returns the spine bone a later breath can pitch without accumulating.
 */
export function applyRelaxedStandingPose(root: THREE.Object3D): AvatarRestPose {
  const bones = indexBones(root);
  const left = matchLimb(bones, "left");
  const right = matchLimb(bones, "right");
  poseSide(root, "left", left.upper, left.forearm, left.hand);
  poseSide(root, "right", right.upper, right.forearm, right.hand);
  const breathBone = findBreathBone(bones);
  return {
    left: left.match,
    right: right.match,
    breathBoneName: breathBone?.name ?? null,
    breathBone,
    breathRest: breathBone ? breathBone.quaternion.clone() : null,
  };
}

export function idleBreathAngle(elapsedSeconds: number): number {
  return (
    Math.sin(elapsedSeconds * AVATAR_IDLE_BREATH_SPEED) *
    AVATAR_IDLE_BREATH_RADIANS
  );
}

/** Pitch one spine bone around the figure's local X, always from its rest. */
export function applyIdleBreath(
  pose: AvatarRestPose,
  root: THREE.Object3D,
  elapsedSeconds: number,
): void {
  if (!pose.breathBone || !pose.breathRest) return;
  pose.breathBone.quaternion.copy(pose.breathRest);
  const angle = idleBreathAngle(elapsedSeconds);
  if (angle === 0) return;
  const axis = new THREE.Vector3(1, 0, 0).transformDirection(root.matrixWorld);
  applyWorldDelta(
    pose.breathBone,
    new THREE.Quaternion().setFromAxisAngle(axis, angle),
  );
}

/**
 * An idle clip wins over the procedural hang. Bind, T-pose and A-pose clips
 * are not idle motion even when they are the only clip in the file.
 */
export function selectIdleClip<T extends { name: string }>(
  clips: readonly T[],
): T | null {
  const usable = clips.filter(
    (clip) => IDLE_CLIP.test(clip.name) && !BIND_CLIP.test(clip.name),
  );
  if (usable.length === 0) return null;
  return usable.find((clip) => /idle/i.test(clip.name)) ?? usable[0];
}
