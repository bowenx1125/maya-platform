import * as THREE from "three";
import {
  EGG_PROFILE as P,
  eggRadius,
  eggFrontZ,
  eggMouthBeat,
} from "./egg-profile";

export type EggModel = {
  root: THREE.Object3D;
  dispose: () => void;
  frame: (time: number, playing: boolean, reduced: boolean) => void;
};

/** Adapt the supplied GLB, preserving its shell topology and limb meshes. */
export function prepareEggModel(root: THREE.Object3D): EggModel {
  const shell = root.getObjectByName("Shell") as THREE.Mesh;
  const sourceMouth = root.getObjectByName("Mouth") as THREE.Mesh;
  if (!shell || !sourceMouth) throw new Error("egg_asset_invalid");
  const joints: THREE.Vector3[] = [];
  const joins: THREE.Mesh[] = [];
  const aoScale = { value: 1 };
  const aoBottom = { value: P.bottom as number };
  const worldScale = new THREE.Vector3();
  const worldBase = new THREE.Vector3();
  const grainBytes = new Uint8Array(128 * 128 * 4);
  let seed = 427;
  for (let i = 0; i < 128 * 128; i++) {
    seed = (1664525 * seed + 1013904223) >>> 0;
    const value = 120 + Math.round(16 * (seed / 4294967296 - 0.5));
    grainBytes.set([value, value, value, 255], i * 4);
  }
  const grain = new THREE.DataTexture(grainBytes, 128, 128);
  grain.wrapS = grain.wrapT = THREE.RepeatWrapping;
  grain.repeat.set(6, 6);
  grain.needsUpdate = true;
  const material = new THREE.MeshPhysicalMaterial({
    color: "#BE8032",
    bumpMap: grain,
    bumpScale: 0.0012,
    roughness: 0.66,
    sheen: 0.1,
    sheenColor: new THREE.Color("#E5AD68"),
    sheenRoughness: 0.9,
  });
  material.onBeforeCompile = (shader) => {
    shader.uniforms.clayJoin = { value: joints };
    shader.uniforms.clayScale = aoScale;
    shader.uniforms.clayBottom = aoBottom;
    shader.vertexShader = shader.vertexShader
      .replace(
        "#include <common>",
        "#include <common>\nvarying vec3 vClayWorld;",
      )
      .replace(
        "#include <worldpos_vertex>",
        "#include <worldpos_vertex>\nvClayWorld = (modelMatrix * vec4(transformed,1.0)).xyz;",
      );
    const physical = THREE.ShaderChunk.lights_physical_pars_fragment.replace(
      "reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseContribution );",
      `float rawNL = dot(geometryNormal,directLight.direction);
       float wrappedNL = pow(clamp((rawNL+0.32)/1.32,0.0,1.0),1.35);
       vec3 wrapTint = mix(vec3(1.0,0.45,0.12),vec3(1.0),smoothstep(0.0,0.6,rawNL));
       reflectedLight.directDiffuse += directLight.color*wrappedNL*wrapTint*BRDF_Lambert(material.diffuseContribution);
       float thinEdge = pow(1.0-clamp(dot(geometryNormal,geometryViewDir),0.0,1.0),3.5);
       float scatter = pow(clamp(dot(-directLight.direction,geometryViewDir),0.0,1.0),2.0);
       reflectedLight.directDiffuse += directLight.color*material.diffuseContribution*vec3(0.25,0.085,0.012)*thinEdge*(0.12+0.88*scatter);`,
    );
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <lights_physical_pars_fragment>", physical)
      .replace(
        "#include <common>",
        "#include <common>\nvarying vec3 vClayWorld;\nuniform vec3 clayJoin[4];\nuniform float clayScale;\nuniform float clayBottom;",
      )
      .replace(
        "#include <opaque_fragment>",
        `float ao=1.0;
        for(int i=0;i<4;i++){vec3 q=vClayWorld-clayJoin[i];ao*=1.0-0.22*exp(-dot(q,q)/(0.018*clayScale*clayScale));}
        outgoingLight*=ao*mix(0.76,1.0,smoothstep(clayBottom+0.09*clayScale,clayBottom+0.54*clayScale,vClayWorld.y));
        #include <opaque_fragment>`,
      );
  };
  material.customProgramCacheKey = () => "egg-amber-c2-v1";
  root.traverse((object) => {
    if (object instanceof THREE.Mesh) object.geometry = object.geometry.clone();
  });
  sourceMouth.material = Array.isArray(sourceMouth.material)
    ? sourceMouth.material.map((m) => m.clone())
    : sourceMouth.material.clone();
  const g = shell.geometry;
  const pos = g.attributes.position;
  g.computeBoundingBox();
  const min = g.boundingBox!.min.y,
    height = g.boundingBox!.max.y - min;
  // Preserve source topology, with circular rings so the analytic mouth
  // projection stays on the same surface from every viewing direction.
  for (let i = 0; i < pos.count; i++) {
    const y = pos.getY(i),
      h = (y - min) / height;
    const radius = Math.hypot(pos.getX(i), pos.getZ(i));
    const factor = radius > 0.00001 ? eggRadius(h) / radius : 0;
    pos.setXYZ(
      i,
      pos.getX(i) * factor,
      P.bottom + P.height * h,
      pos.getZ(i) * factor,
    );
  }
  shell.position.set(0, 0, 0);
  shell.scale.set(1, 1, 1);
  pos.needsUpdate = true;
  g.computeVertexNormals();
  g.computeBoundingSphere();
  const fillet = (
    name: string,
    x: number,
    y: number,
    z: number,
    scale: number[],
  ) => {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 32, 20), material);
    mesh.name = name;
    mesh.position.set(x, y, z);
    mesh.scale.set(scale[0], scale[1], scale[2]);
    root.add(mesh);
    joints.push(mesh.position.clone());
    joins.push(mesh);
    return mesh;
  };
  const handY = P.bottom + P.height * P.handHeight;
  const hands: { mesh: THREE.Mesh; join: THREE.Mesh; sign: number }[] = [];
  for (const [suffix, sign] of [
    ["L", -1],
    ["R", 1],
  ] as const) {
    const hand = root.getObjectByName(`Hand_${suffix}`) as THREE.Mesh;
    hand.material = material;
    hand.scale.set(0.115, 0.16, 0.14);
    hand.position.set(sign * (eggRadius(P.handHeight) + 0.025), handY, 0.085);
    hand.rotation.set(0, 0, sign * 0.22);
    const join = fillet(
      `Fillet_Hand_${suffix}`,
      sign * (eggRadius(P.handHeight) - 0.045),
      handY + 0.035,
      0.075,
      [0.12, 0.17, 0.145],
    );
    hands.push({ mesh: hand, join, sign });
  }
  for (const [suffix, sign] of [
    ["L", -1],
    ["R", 1],
  ] as const) {
    const foot = root.getObjectByName(`Foot_${suffix}`) as THREE.Mesh;
    foot.material = material;
    foot.scale.set(0.145, 0.105, 0.23);
    foot.position.set(sign * P.footX, 0.105, 0.17);
    foot.rotation.set(0, sign * 0.05, 0);
    fillet(
      `Fillet_Foot_${suffix}`,
      sign * P.footX,
      0.27,
      0.105,
      [0.092, 0.18, 0.13],
    );
  }
  shell.material = material;
  sourceMouth.visible = false;
  const mouthGeometry = new THREE.BufferGeometry();
  const count = 64,
    vertices = new Float32Array((count + 1) * 2 * 3),
    indices: number[] = [];
  for (let i = 0; i < count; i++) {
    const a = i * 2;
    indices.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
  }
  mouthGeometry.setAttribute(
    "position",
    new THREE.BufferAttribute(vertices, 3),
  );
  mouthGeometry.setIndex(indices);
  const mouth = new THREE.Mesh(
    mouthGeometry,
    new THREE.MeshStandardMaterial({
      color: "#250D05",
      roughness: 0.88,
      side: THREE.DoubleSide,
    }),
  );
  root.add(mouth);
  let weight = 0,
    envelope = 0,
    last = 0,
    started = 0,
    wasPlaying = false;
  const frame = (time: number, playing: boolean, reduced: boolean) => {
    const dt = Math.max(0, Math.min(time - last, 0.12));
    last = time;
    if (playing && !wasPlaying) started = time;
    wasPlaying = playing;
    const local = time - started;
    weight = playing ? eggMouthBeat(local) : Math.max(0, weight - dt / 0.12);
    envelope = playing
      ? Math.min(1, envelope + dt / 0.15)
      : Math.max(0, envelope - dt / 0.65);
    const stretch = reduced ? 0 : 0.026 * weight;
    shell.scale.set(1 - stretch * 0.42, 1 + stretch, 1 - stretch * 0.3);
    shell.position.y = -P.bottom * stretch;
    const anchor = P.bottom + P.height * P.mouthHeight;
    const width = 2 * eggRadius(P.mouthHeight) * P.mouthWidthRatio;
    for (let i = 0; i <= count; i++) {
      const u = (i / count) * 2 - 1,
        shape = Math.pow(Math.max(0, 1 - u * u), 0.78),
        x = (u * width) / 2;
      const top = anchor + 0.055 * u * u + weight * 0.025 * shape;
      for (let j = 0; j < 2; j++) {
        const y =
          j === 0
            ? top
            : anchor + 0.055 * u * u - 0.014 * shape - weight * 0.15 * shape;
        mouthGeometry.attributes.position.setXYZ(
          i * 2 + j,
          x * (1 - stretch * 0.42),
          y * (1 + stretch) - P.bottom * stretch,
          eggFrontZ(x, y) * (1 - stretch * 0.3) + 0.014,
        );
      }
    }
    mouthGeometry.attributes.position.needsUpdate = true;
    mouthGeometry.computeVertexNormals();
    for (const { mesh, join, sign } of hands) {
      const lift =
        !reduced && sign === 1
          ? 0.14 *
            (0.5 - 0.5 * Math.cos((2 * Math.PI * local) / 2.4)) *
            envelope
          : 0;
      const y = handY + lift,
        r = eggRadius((y - P.bottom) / P.height);
      mesh.position.set(sign * (r + 0.025), y, 0.085);
      mesh.rotation.set(-lift * 1.3, 0, sign * (0.22 + lift * 2.4));
      join.position.set(sign * (r - 0.045), y + 0.035, 0.075);
    }
    root.rotation.z = reduced
      ? 0
      : THREE.MathUtils.degToRad(3) *
        Math.sin((2 * Math.PI * local) / 3.4) *
        envelope;
    root.rotation.x = 0;
    root.updateMatrixWorld(true);
    joins.forEach((join, index) => join.getWorldPosition(joints[index]));
    aoScale.value = root.getWorldScale(worldScale).y;
    aoBottom.value = root.localToWorld(worldBase.set(0, P.bottom, 0)).y;
  };
  frame(0, false, true);
  return { root, frame, dispose: () => grain.dispose() };
}
