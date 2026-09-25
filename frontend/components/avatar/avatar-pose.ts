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
};

/**
 * Root-local hang weights. Registered figures face +Z and +Y is up.
 * `lateral` is outward, `down` is toward the feet, `forward` is toward +Z.
 * A fitted body can hang near the sides. Loose robe cloth is skinned to the
 * same arm bones, and a full drop pulls those sleeves into an X across the
 * waist, so robe profiles stay nearer a relaxed A-pose.
 */
export type AvatarHangWeights = {
  lateral: number;
  down: number;
  forward: number;
};

export type AvatarHangProfile = {
  upperArm: AvatarHangWeights;
  forearm: AvatarHangWeights;
  /**
   * 1 rotates twist and sleeve helpers with the limb. 0 leaves them in the
   * bind pose. Values in between are a counter-rotation back toward the bind.
   */
  twistFollow: number;
};

function hangWeights(
  dropDegrees: number,
  forward: number,
  lateralScale = 1,
): AvatarHangWeights {
  const drop = THREE.MathUtils.degToRad(dropDegrees);
  return {
    lateral: Math.cos(drop) * lateralScale,
    down: Math.sin(drop),
    forward,
  };
}

export function makeHangProfile(options: {
  upperDropDegrees: number;
  forearmDropDegrees: number;
  upperForward?: number;
  forearmForward?: number;
  forearmLateralScale?: number;
  twistFollow?: number;
}): AvatarHangProfile {
  return {
    upperArm: hangWeights(
      options.upperDropDegrees,
      options.upperForward ?? 0.1,
    ),
    forearm: hangWeights(
      options.forearmDropDegrees,
      options.forearmForward ?? 0.22,
      options.forearmLateralScale ?? 0.82,
    ),
    twistFollow: options.twistFollow ?? 1,
  };
}

/** Close to the sides. Used for the fitted Ready Player Me body. */
export const AVATAR_FITTED_HANG: AvatarHangProfile = makeHangProfile({
  upperDropDegrees: 74,
  forearmDropDegrees: 68,
  upperForward: 0.12,
  forearmForward: 0.38,
  forearmLateralScale: 0.7,
  twistFollow: 1,
});

/**
 * Loose robe cloth is skinned to the arm. A full drop pulls the wide sleeves
 * into an X across the belt. 55° down from a T-pose, with the elbow bent a
 * little further and the hand slightly forward, is the lowest hang that stays
 * clear of that cross on both scholar robes. Twist and sleeve helpers follow
 * the limb; leaving them in the bind pose holds the sleeve up in the air.
 */
export const AVATAR_ROBE_HANG: AvatarHangProfile = makeHangProfile({
  upperDropDegrees: 55,
  forearmDropDegrees: 67,
  upperForward: 0.08,
  forearmForward: 0.22,
  forearmLateralScale: 0.88,
  twistFollow: 1,
});

const PALM_BACK = 0.22;

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

function boneNameTokens(name: string): string[] {
  return name
    .replace(/^mixamorig(?::|_|-)*/i, "")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((token) => token.length > 0);
}

/**
 * Side is a whole token (`left`, `l`), not a trailing letter. `Roll` stays
 * unsided; `upperarm_l` and `LeftArm` do not.
 */
export function boneSide(name: string): AvatarPoseSide | null {
  const tokens = boneNameTokens(name);
  for (let index = tokens.length - 1; index >= 0; index -= 1) {
    const token = tokens[index];
    if (token === "l" || token === "left") return "left";
    if (token === "r" || token === "right") return "right";
  }
  return null;
}

export function hangProfileForAsset(assetUrl: string): AvatarHangProfile {
  if (/elder-scholar|noble-scholar/i.test(assetUrl)) return AVATAR_ROBE_HANG;
  return AVATAR_FITTED_HANG;
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

function partialDelta(
  worldDelta: THREE.Quaternion,
  amount: number,
): THREE.Quaternion | null {
  if (amount <= 0) return null;
  if (amount >= 1) return worldDelta;
  return new THREE.Quaternion().slerp(worldDelta, amount);
}

/**
 * Roll the forearm around its own axis so the palm faces the thigh.
 * The hand stays in its bind orientation relative to the forearm, which keeps
 * jacket cuffs from flaring at the wrist.
 */
function rollPalmInward(
  root: THREE.Object3D,
  forearm: THREE.Object3D,
  hand: THREE.Object3D,
  lateral: number,
  twistFollow: number,
  side: AvatarPoseSide,
): void {
  const digit = primaryDigit(hand);
  const thumb = proximalThumb(hand);
  if (!digit || !thumb) return;
  const origin = hand.getWorldPosition(new THREE.Vector3());
  const toDigit = digit.getWorldPosition(new THREE.Vector3()).sub(origin);
  const toThumb = thumb.getWorldPosition(new THREE.Vector3()).sub(origin);
  const axis = hand
    .getWorldPosition(new THREE.Vector3())
    .sub(forearm.getWorldPosition(new THREE.Vector3()));
  if (
    toDigit.lengthSq() < 1e-8 ||
    toThumb.lengthSq() < 1e-8 ||
    axis.lengthSq() < 1e-8
  ) {
    return;
  }
  axis.normalize();
  // Mirrored right-hand rigs flip the cross product, so the same order points
  // out of the back of the hand. Negate that side before rolling the palm in.
  const palm = new THREE.Vector3().crossVectors(toDigit, toThumb).normalize();
  if (lateral < 0) palm.negate();
  const desired = new THREE.Vector3(-lateral, 0, -PALM_BACK)
    .normalize()
    .transformDirection(root.matrixWorld);
  const currentFlat = palm.clone().projectOnPlane(axis);
  const desiredFlat = desired.clone().projectOnPlane(axis);
  if (currentFlat.lengthSq() < 1e-8 || desiredFlat.lengthSq() < 1e-8) return;
  const worldDelta = new THREE.Quaternion().setFromUnitVectors(
    currentFlat.normalize(),
    desiredFlat.normalize(),
  );
  applyWorldDelta(forearm, worldDelta);
  const twistDelta = partialDelta(worldDelta, twistFollow);
  if (!twistDelta) return;
  for (const twist of twistCompanions(root, forearm, "fore", side)) {
    applyWorldDelta(twist, twistDelta);
  }
}

function applyTwistDelta(
  root: THREE.Object3D,
  primary: THREE.Object3D,
  segment: "upper" | "fore",
  side: AvatarPoseSide,
  worldDelta: THREE.Quaternion,
  twistFollow: number,
): void {
  const delta = partialDelta(worldDelta, twistFollow);
  if (!delta) return;
  for (const twist of twistCompanions(root, primary, segment, side)) {
    applyWorldDelta(twist, delta);
  }
}

function poseSide(
  root: THREE.Object3D,
  side: AvatarPoseSide,
  upper: THREE.Object3D | null,
  forearm: THREE.Object3D | null,
  hand: THREE.Object3D | null,
  profile: AvatarHangProfile,
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
      hangDirection(root, lateral, profile.upperArm),
    );
    if (delta) {
      applyTwistDelta(root, upper, "upper", side, delta, profile.twistFollow);
    }
  }
  root.updateMatrixWorld(true);
  if (forearm && hand && hasDescendant(forearm, hand)) {
    const delta = swingChildToward(
      forearm,
      hand,
      hangDirection(root, lateral, profile.forearm),
    );
    if (delta) {
      applyTwistDelta(root, forearm, "fore", side, delta, profile.twistFollow);
    }
    root.updateMatrixWorld(true);
    rollPalmInward(root, forearm, hand, lateral, profile.twistFollow, side);
  }
}

/**
 * Hang both arms from the bind pose. Feet, head, jaw and face bones are left
 * alone.
 */
export function applyRelaxedStandingPose(
  root: THREE.Object3D,
  profile: AvatarHangProfile = AVATAR_FITTED_HANG,
): AvatarRestPose {
  const bones = indexBones(root);
  const left = matchLimb(bones, "left");
  const right = matchLimb(bones, "right");
  poseSide(root, "left", left.upper, left.forearm, left.hand, profile);
  poseSide(root, "right", right.upper, right.forearm, right.hand, profile);
  return {
    left: left.match,
    right: right.match,
  };
}
