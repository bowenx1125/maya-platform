import * as THREE from "three";

/**
 * Synthetic mouth morph for figures whose meshes ship no blendshapes
 * (Tripo geometry + Mixamo rigging has no facial morphs and no jaw bone).
 *
 * The morph drops the lower-front "jaw" region of the head-skinned vertices
 * along the skull axis, which reads as a mouth opening at stage distance.
 * Viseme/procedural mouth values (0..1) then drive the same
 * `mouthOpen` dictionary key the built-in blendshape figures use, so the
 * stage's existing speech pipeline needs no per-rig branching.
 */

export interface MouthRegionSample {
  /** Vertex index into the position attribute. */
  index: number;
  /** 0..1 drop weight; the chin moves most, the mouth line least. */
  weight: number;
}

const REGION_TOP = 0.38;
const MIN_REGION_VERTICES = 24;
const DROP_FRACTION_OF_SKULL = 0.09;

/**
 * Pure region selection: vertices that are (a) mostly skinned to the head
 * joint and (b) sit on the lower part of the skull (below REGION_TOP of the
 * head->headTop axis span). `positions` are world-space rest positions;
 * `headWeights` is the summed skin weight of the head joint per vertex.
 */
export function selectMouthRegion(
  positions: readonly THREE.Vector3[],
  headWeights: readonly number[],
  headPos: THREE.Vector3,
  skullAxis: THREE.Vector3,
  skullSpan: number,
): MouthRegionSample[] {
  const samples: MouthRegionSample[] = [];
  if (skullSpan <= 1e-6) return samples;
  const inv = 1 / skullSpan;
  for (let i = 0; i < positions.length; i++) {
    if ((headWeights[i] ?? 0) < 0.35) continue;
    const t =
      (positions[i].x - headPos.x) * skullAxis.x +
      (positions[i].y - headPos.y) * skullAxis.y +
      (positions[i].z - headPos.z) * skullAxis.z;
    const tNorm = t * inv;
    if (tNorm < -0.05 || tNorm > REGION_TOP) continue;
    const weight = Math.min(1, Math.max(0, (REGION_TOP - tNorm) / REGION_TOP));
    samples.push({ index: i, weight });
  }
  return samples;
}

export function findHeadTopBone(root: THREE.Object3D): THREE.Object3D | null {
  let found: THREE.Object3D | null = null;
  root.traverse((object) => {
    if (found) return;
    if (/headtop|head_?top|head\s*end/i.test(object.name)) found = object;
  });
  return found;
}

function headJointIndex(
  mesh: THREE.SkinnedMesh,
  headBone: THREE.Object3D,
): number {
  const bones = mesh.skeleton?.bones ?? [];
  for (let i = 0; i < bones.length; i++) {
    if (bones[i] === headBone) return i;
  }
  return -1;
}

/**
 * Attach (or re-wire) a synthetic `mouthOpen` morph on a mesh. Idempotent per
 * geometry: SkeletonUtils.clone shares geometry across seats, so the second
 * seat on the same template only re-registers dictionary/influences.
 * Returns true when the mesh ends up with a usable mouthOpen morph.
 */
export function attachSyntheticMouth(
  mesh: THREE.SkinnedMesh,
  headBone: THREE.Object3D,
  headTopBone: THREE.Object3D | null,
): boolean {
  const existing = mesh.morphTargetDictionary?.mouthOpen;
  if (existing !== undefined && mesh.morphTargetInfluences) return true;
  if (mesh.morphTargetDictionary?.jawOpen !== undefined) return false;

  const geometry = mesh.geometry as THREE.BufferGeometry & {
    userData: Record<string, unknown>;
  };
  const marker = geometry.userData.__syntheticMouth as
    { index: number } | undefined;

  if (marker) {
    mesh.morphTargetDictionary = {
      ...(mesh.morphTargetDictionary ?? {}),
      mouthOpen: marker.index,
    };
    mesh.morphTargetInfluences = mesh.morphTargetInfluences ?? [];
    while (mesh.morphTargetInfluences.length <= marker.index) {
      mesh.morphTargetInfluences.push(0);
    }
    return true;
  }

  const joint = headJointIndex(mesh, headBone);
  if (joint < 0 || !mesh.skeleton) return false;

  // Rest-pose world positions via the skinned vertex path.
  mesh.skeleton.update();
  const vertexCount = geometry.attributes.position?.count ?? 0;
  const positions: THREE.Vector3[] = [];
  const headWeights: number[] = [];
  const skinIndex = geometry.attributes.skinIndex;
  const skinWeight = geometry.attributes.skinWeight;
  const v = new THREE.Vector3();
  for (let i = 0; i < vertexCount; i++) {
    mesh.getVertexPosition(i, v);
    positions.push(v.clone());
    let w = 0;
    if (skinIndex && skinWeight) {
      for (let k = 0; k < 4; k++) {
        if (skinIndex.getComponent(i, k) === joint) {
          w += skinWeight.getComponent(i, k);
        }
      }
    }
    headWeights.push(w);
  }

  // getVertexPosition returns mesh-local space; convert bone anchors into
  // the same space before measuring along the skull axis.
  const toLocal = (world: THREE.Vector3): THREE.Vector3 =>
    mesh.worldToLocal(world.clone());
  const headPos = toLocal(headBone.getWorldPosition(new THREE.Vector3()));
  let skullAxis = new THREE.Vector3(0, 1, 0).transformDirection(
    mesh.matrixWorld.clone().invert(),
  );
  let skullSpan = 0;
  if (headTopBone) {
    const top = toLocal(headTopBone.getWorldPosition(new THREE.Vector3()));
    skullAxis = top.sub(headPos);
    skullSpan = skullAxis.length();
    if (skullSpan > 1e-6) skullAxis.normalize();
    else skullSpan = 0;
  }
  if (skullSpan <= 1e-6) {
    // No headTop joint (Mixamo rigs): estimate the skull span from the
    // vertical extent of the head-weighted vertices instead.
    let lo = Infinity,
      hi = -Infinity;
    for (let i = 0; i < positions.length; i++) {
      if ((headWeights[i] ?? 0) < 0.35) continue;
      lo = Math.min(lo, positions[i].y);
      hi = Math.max(hi, positions[i].y);
    }
    skullSpan = hi - lo;
  }
  if (skullSpan <= 1e-6) skullSpan = 1e-6;

  const region = selectMouthRegion(
    positions,
    headWeights,
    headPos,
    skullAxis,
    Math.max(skullSpan, 1e-6),
  );
  if (region.length < MIN_REGION_VERTICES) return false;

  const base = geometry.attributes.position;
  const drop = Math.max(skullSpan, 1e-6) * DROP_FRACTION_OF_SKULL;
  const morphed = new Float32Array(vertexCount * 3);
  for (let i = 0; i < vertexCount; i++) {
    morphed[i * 3] = base.getX(i);
    morphed[i * 3 + 1] = base.getY(i);
    morphed[i * 3 + 2] = base.getZ(i);
  }
  for (const { index, weight } of region) {
    morphed[index * 3] -= skullAxis.x * drop * weight;
    morphed[index * 3 + 1] -= skullAxis.y * drop * weight;
    morphed[index * 3 + 2] -= skullAxis.z * drop * weight;
  }

  const morphAttributes = geometry.morphAttributes as {
    position: THREE.BufferAttribute[];
  };
  morphAttributes.position = morphAttributes.position ?? [];
  const index = morphAttributes.position.length;
  morphAttributes.position.push(
    new THREE.BufferAttribute(morphed, 3) as THREE.BufferAttribute,
  );
  geometry.userData.__syntheticMouth = { index };

  mesh.morphTargetDictionary = {
    ...(mesh.morphTargetDictionary ?? {}),
    mouthOpen: index,
  };
  mesh.morphTargetInfluences = mesh.morphTargetInfluences ?? [];
  while (mesh.morphTargetInfluences.length <= index) {
    mesh.morphTargetInfluences.push(0);
  }
  const material = mesh.material as THREE.Material | THREE.Material[];
  for (const m of Array.isArray(material) ? material : [material]) {
    m.needsUpdate = true;
  }
  return true;
}
