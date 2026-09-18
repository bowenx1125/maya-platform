import * as THREE from "three";
import { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { clone as cloneSkinned } from "three/examples/jsm/utils/SkeletonUtils.js";

import {
  avatarMotionFrame,
  expressionForAvatarState,
  type AvatarConfig,
  type AvatarExpression,
  type AvatarState,
} from "../avatar";
import {
  STAGE_CHARACTER_ASSETS,
  STAGE_DECODER_PATH,
  isStageAssetUrl,
} from "./assets";

export type StageCharacter = {
  id: string;
  slot: "A" | "B" | "C" | "D" | "E";
  name: string;
  config: AvatarConfig;
};

export type StageAnchor = {
  id: string;
  /** Head position in CSS pixels within the canvas box. */
  x: number;
  y: number;
  /** The same x as a 0-1 fraction of the canvas, for side-of-stage decisions. */
  nx: number;
  /** False while the head is behind the camera or outside the frustum. */
  visible: boolean;
};

export type ScholarStageOptions = {
  canvas: HTMLCanvasElement;
  onReady?: () => void;
  onError?: (error: Error) => void;
  /** Head anchors, in CSS pixels, once per frame. */
  onAnchors?: (anchors: StageAnchor[]) => void;
};

/** Skin, by the platform's own avatar themes. */
const SKIN_COLORS: Record<AvatarConfig["material_theme"], string> = {
  demo: "#d5a27c",
  warm_sand: "#c88b68",
  cool_slate: "#a9b9c9",
  civic_olive: "#a49a75",
};

/** Clothing, so five copies of one figure read as five different speakers. */
const OUTFIT_TINTS: Record<AvatarConfig["material_theme"], string> = {
  demo: "#8e93a8",
  warm_sand: "#c9a077",
  cool_slate: "#7f93ab",
  civic_olive: "#8f9670",
};

const EYE_COLORS: Record<string, string> = {
  default: "#72523e",
  brown: "#5b3726",
  hazel: "#8a6a3e",
  blue: "#5d86b2",
  green: "#5b8968",
  gray: "#7e8790",
};

/**
 * The same expression vocabulary the platform's avatar preview uses, so a
 * config a student chose in the editor reads the same way on the bench.
 */
const EXPRESSION_TARGETS: Record<AvatarExpression, Record<string, number>> = {
  neutral: {},
  attentive: { browInnerUp: 0.5, eyeWideLeft: 0.35, eyeWideRight: 0.35 },
  happy: { mouthSmile: 0.75, mouthSmileLeft: 0.55, mouthSmileRight: 0.55 },
  serious_angry: { browDownLeft: 0.55, browDownRight: 0.55, mouthPress: 0.25 },
  sad: { mouthFrownLeft: 0.55, mouthFrownRight: 0.55, browInnerUp: 0.3 },
};

const EXPRESSION_STRENGTH: Record<AvatarConfig["expression_strength"], number> =
  { low: 0.35, medium: 0.65, high: 1 };

/** How far the speaker leans toward the table, in model heights. */
const SPEAKER_STEP_FORWARD = 0.16;
const NORMALISED_HEIGHT = 1.7;
const ANCHOR_INTERVAL_MS = 60;
const CAMERA_FOV_DEGREES = 34;
const DEFAULT_CAMERA_Z = 3.6;
const CAMERA_HEIGHT = 2.3;
const CAMERA_TARGET = new THREE.Vector3(0, 1.0, 0.2);
const CAMERA_DEPTH_MARGIN = 0.35;
const CAMERA_EDGE_MARGIN = 1.08;

const TABLE_RADIUS = 0.95;
const TABLE_TOP_Y = 0.72;
const TABLE_CENTER_Z = 0.2;
// The bundled figures stand; hide lower legs until seated assets are approved.
const SEAT_CLIP_Y = 0.22;
// Spread wide enough that five upper bodies read as distinct speakers from
// the fixed camera without breaking the roundtable composition.
const SEAT_RADIUS = 2.15;
const SEAT_MAX_ARC = 2.0;
const SEAT_ARC_PER_SEAT = 0.44;
/** Jaw opening angle while a character is speaking, in radians. */
const JAW_OPEN_ANGLE = 0.28;

type MorphMesh = THREE.Mesh & {
  morphTargetDictionary?: Record<string, number>;
  morphTargetInfluences?: number[];
};

type Character = {
  spec: StageCharacter;
  root: THREE.Object3D;
  meshes: MorphMesh[];
  headBone: THREE.Object3D | null;
  headRest: THREE.Quaternion | null;
  neckBone: THREE.Object3D | null;
  neckRest: THREE.Quaternion | null;
  torsoBone: THREE.Object3D | null;
  torsoRest: THREE.Quaternion | null;
  jawBone: THREE.Object3D | null;
  jawRest: THREE.Quaternion | null;
  homeZ: number;
  state: AvatarState;
  stateStartedAt: number;
  forward: number;
};

/** Bone naming differs between the two purchased figures. */
const JAW_BONE_NAMES = ["bone_jaw", "jawjoint_m"];
const HEAD_BONE_NAMES = ["head", "head_m"];

function findBone(
  root: THREE.Object3D,
  names: string[],
): THREE.Object3D | null {
  let found: THREE.Object3D | null = null;
  root.traverse((object) => {
    if (found) return;
    if (names.includes(object.name.toLowerCase())) found = object;
  });
  return found;
}

function isMorphMesh(object: THREE.Object3D): object is MorphMesh {
  return Boolean((object as MorphMesh).isMesh);
}

function poseArms(root: THREE.Object3D): void {
  for (const suffix of ["l", "r"]) {
    const shoulder = findBone(root, [
      `upperarm_${suffix}`,
      `shoulder_${suffix}`,
    ]);
    const elbow = findBone(root, [`lowerarm_${suffix}`, `elbow_${suffix}`]);
    if (!shoulder || !elbow) continue;
    root.updateMatrixWorld(true);
    const before = elbow.getWorldPosition(new THREE.Vector3()).y;
    shoulder.rotateZ(0.1);
    root.updateMatrixWorld(true);
    const direction = Math.sign(
      elbow.getWorldPosition(new THREE.Vector3()).y - before,
    );
    shoulder.rotateZ(-0.1);
    shoulder.rotateZ(direction > 0 ? -1.35 : 1.35);
  }
}

function disposeObject(root: THREE.Object3D, disposeGeometry = true): void {
  const seen = new Set<THREE.Material>();
  root.traverse((object) => {
    if (!isMorphMesh(object)) return;
    if (disposeGeometry) object.geometry.dispose();
    const materials = Array.isArray(object.material)
      ? object.material
      : [object.material];
    for (const material of materials) {
      if (seen.has(material)) continue;
      seen.add(material);
      material.dispose();
    }
  });
}

/**
 * One WebGL context, one render loop, every speaker in it.
 *
 * Two figures are loaded once and cloned per speaker. Neither purchased
 * model contains speech clips, so their jaw bones carry the first pass.
 */
export class ScholarStage {
  private readonly canvas: HTMLCanvasElement;
  private readonly scene: THREE.Scene;
  private readonly camera: THREE.PerspectiveCamera;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly loader = new GLTFLoader();
  private readonly draco = new DRACOLoader();
  private readonly seatClipPlane = new THREE.Plane(
    new THREE.Vector3(0, 1, 0),
    -SEAT_CLIP_Y,
  );
  private readonly onReady?: () => void;
  private readonly onError?: (error: Error) => void;
  private readonly onAnchors?: (anchors: StageAnchor[]) => void;

  private templates: THREE.Object3D[] = [];
  private templateScales: number[] = [];
  private loading = 0;
  private table: THREE.Group | null = null;
  private readonly characters: Character[] = [];
  private pending: StageCharacter[] | null = null;
  private frame: number | null = null;
  private startedAt = performance.now();
  private lastAnchorAt = 0;
  private width = 0;
  private height = 0;
  private disposed = false;
  private resting = true;
  private reducedMotion = false;

  private readonly projection = new THREE.Vector3();
  private readonly offsetEuler = new THREE.Euler();
  private readonly offsetQuat = new THREE.Quaternion();
  private readonly clock = new THREE.Clock();
  private readonly resizeHandler = () => this.resize();

  constructor(options: ScholarStageOptions) {
    this.canvas = options.canvas;
    this.onReady = options.onReady;
    this.onError = options.onError;
    this.onAnchors = options.onAnchors;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(CAMERA_FOV_DEGREES, 1, 0.1, 60);
    // A fixed high seat across the table: the whole composition is built for
    // this one perspective, so the camera never moves — only the framing
    // distance adapts as the roster grows.
    this.camera.position.set(0, CAMERA_HEIGHT, DEFAULT_CAMERA_Z);
    this.camera.lookAt(CAMERA_TARGET);
    this.scene.add(this.camera);

    this.scene.add(new THREE.HemisphereLight(0xfff6ea, 0x4a5464, 2.1));
    const key = new THREE.DirectionalLight(0xfff3e2, 1.9);
    key.position.set(2.4, 4.2, 3.6);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xcfdcf2, 0.55);
    fill.position.set(-3, 1.4, 2);
    this.scene.add(fill);

    this.buildTable();

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      alpha: true,
      antialias: true,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.localClippingEnabled = true;

    if (typeof window.matchMedia === "function") {
      this.reducedMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
    }

    this.draco.setDecoderPath(STAGE_DECODER_PATH);
    this.loader.setDRACOLoader(this.draco);
    window.addEventListener("resize", this.resizeHandler, { passive: true });
    this.resize();
    this.load();
  }

  setCharacters(specs: StageCharacter[]): void {
    if (this.loading !== 0 || this.templates.some((template) => !template)) {
      this.pending = specs;
      this.updateCameraFraming();
      return;
    }
    this.rebuild(specs);
  }

  /** Before the first turn and after the last, the bench is simply calm. */
  setResting(resting: boolean): void {
    this.resting = resting;
  }

  setVisual(id: string, state: AvatarState): void {
    const character = this.characters.find((item) => item.spec.id === id);
    if (!character || character.state === state) return;
    character.state = state;
    character.stateStartedAt = performance.now();
    character.forward = state === "speaking" ? SPEAKER_STEP_FORWARD : 0;
    this.applyExpression(character);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    this.frame = null;
    window.removeEventListener("resize", this.resizeHandler);
    for (const character of this.characters) {
      this.scene.remove(character.root);
      disposeObject(character.root, false);
    }
    this.characters.length = 0;
    for (const template of this.templates) {
      if (template) disposeObject(template);
    }
    this.templates.length = 0;
    this.templateScales.length = 0;
    if (this.table) {
      this.scene.remove(this.table);
      disposeObject(this.table);
      this.table = null;
    }
    this.draco.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }

  private load(): void {
    for (const url of STAGE_CHARACTER_ASSETS) {
      if (!isStageAssetUrl(url)) {
        this.onError?.(new Error("stage_asset_rejected"));
        return;
      }
    }
    this.loading = STAGE_CHARACTER_ASSETS.length;
    this.templates = new Array(STAGE_CHARACTER_ASSETS.length);
    this.templateScales = new Array(STAGE_CHARACTER_ASSETS.length);
    STAGE_CHARACTER_ASSETS.forEach((url, index) => {
      this.loader.load(
        url,
        (gltf) => {
          if (this.disposed || this.loading < 0) {
            disposeObject(gltf.scene);
            return;
          }
          const bounds = new THREE.Box3().setFromObject(gltf.scene);
          const size = bounds.getSize(new THREE.Vector3());
          this.templateScales[index] =
            size.y > 0 ? NORMALISED_HEIGHT / size.y : 1;
          this.templates[index] = gltf.scene;
          this.loading -= 1;
          if (this.loading === 0) {
            if (this.pending) {
              this.rebuild(this.pending);
              this.pending = null;
            }
            this.startLoop();
            this.onReady?.();
          }
        },
        undefined,
        (cause) => {
          if (this.disposed || this.loading < 0) return;
          this.loading = -1;
          this.onError?.(new Error("stage_asset_failed", { cause }));
        },
      );
    });
  }

  private buildTable(): void {
    if (this.table) return;
    const group = new THREE.Group();

    const top = new THREE.Mesh(
      new THREE.CylinderGeometry(TABLE_RADIUS, TABLE_RADIUS, 0.07, 40),
      new THREE.MeshStandardMaterial({ color: 0x8a5a33, roughness: 0.7 }),
    );
    top.position.set(0, TABLE_TOP_Y, TABLE_CENTER_Z);
    group.add(top);

    const pedestal = new THREE.Mesh(
      new THREE.CylinderGeometry(0.16, 0.28, TABLE_TOP_Y - 0.035, 16),
      new THREE.MeshStandardMaterial({ color: 0x5f3d22, roughness: 0.8 }),
    );
    pedestal.position.set(0, (TABLE_TOP_Y - 0.035) / 2, TABLE_CENTER_Z);
    group.add(pedestal);

    this.table = group;
    this.scene.add(group);
  }

  // The far arc keeps faces visible to the classroom while preserving a roundtable layout.
  private seatOffset(
    index: number,
    count: number,
  ): {
    x: number;
    z: number;
  } {
    const arc = Math.min(SEAT_MAX_ARC, (count - 1) * SEAT_ARC_PER_SEAT);
    const angle = count === 1 ? 0 : -arc / 2 + (arc * index) / (count - 1);
    return {
      x: Math.sin(angle) * SEAT_RADIUS,
      z: -Math.cos(angle) * SEAT_RADIUS,
    };
  }

  private rebuild(specs: StageCharacter[]): void {
    for (const character of this.characters) {
      this.scene.remove(character.root);
      disposeObject(character.root, false);
    }
    this.characters.length = 0;
    if (this.templates.length === 0) return;

    const count = Math.max(1, specs.length);
    specs.forEach((spec, index) => {
      // Deterministic variant per seat: load order is the roster order, so a
      // given roster always renders the same mix of the two figures.
      const templateIndex = index % this.templates.length;
      const root = cloneSkinned(
        this.templates[templateIndex] as THREE.Object3D,
      );
      root.scale.setScalar(this.templateScales[templateIndex]);
      const offset = this.seatOffset(index, count);
      const seatX = offset.x;
      const seatZ = TABLE_CENTER_Z + offset.z;
      root.position.set(seatX, -0.42, seatZ);
      // Faces the table centre; the camera sits across it, so everyone reads
      // as being in conversation and mostly toward the viewer.
      root.rotation.y = Math.atan2(-seatX, TABLE_CENTER_Z - seatZ);
      poseArms(root);

      const meshes: MorphMesh[] = [];
      this.styleFigure(root, spec.config, meshes);
      const headBone = findBone(root, HEAD_BONE_NAMES);
      const neckBone = findBone(root, ["neck"]);
      const torsoBone = findBone(root, ["spine2", "spine1", "spine"]);
      const jawBone = findBone(root, JAW_BONE_NAMES);

      const character: Character = {
        spec,
        root,
        meshes,
        headBone,
        headRest: headBone?.quaternion.clone() ?? null,
        neckBone,
        neckRest: neckBone?.quaternion.clone() ?? null,
        torsoBone,
        torsoRest: torsoBone?.quaternion.clone() ?? null,
        jawBone,
        jawRest: jawBone?.quaternion.clone() ?? null,
        homeZ: seatZ,
        state: "idle",
        stateStartedAt: performance.now(),
        forward: 0,
      };
      this.applyExpression(character);
      this.scene.add(root);
      this.characters.push(character);
    });
    this.updateCameraFraming();
  }

  /**
   * Keep heads, table and bubbles inside the visible safe viewport as the
   * roster grows, by pulling the fixed camera straight back along its axis.
   */
  private updateCameraFraming(): void {
    // Imported skinned-mesh bounds include distant rig helpers; frame the
    // authored seat layout instead of letting those helpers shrink the stage.
    const count = this.characters.length || this.pending?.length || 1;
    const arc = Math.min(SEAT_MAX_ARC, (count - 1) * SEAT_ARC_PER_SEAT);
    const outer = Math.sin(arc / 2) * SEAT_RADIUS + 0.62;
    const halfWidth = Math.max(TABLE_RADIUS + 0.55, outer) * CAMERA_EDGE_MARGIN;
    const aspect = Math.max(this.camera.aspect, 0.1);
    const halfFovRadians = THREE.MathUtils.degToRad(CAMERA_FOV_DEGREES / 2);
    const requiredDistance =
      halfWidth / Math.tan(halfFovRadians) / aspect + CAMERA_DEPTH_MARGIN;
    this.camera.position.z = Math.max(DEFAULT_CAMERA_Z, requiredDistance);
    this.camera.lookAt(CAMERA_TARGET);
  }

  private styleFigure(
    root: THREE.Object3D,
    config: AvatarConfig,
    meshes: MorphMesh[],
  ): void {
    const skin = new THREE.Color(
      SKIN_COLORS[config.material_theme] ?? SKIN_COLORS.demo,
    );
    const outfit = new THREE.Color(
      OUTFIT_TINTS[config.material_theme] ?? OUTFIT_TINTS.demo,
    );
    const eye = new THREE.Color(
      EYE_COLORS[config.eye_color ?? "default"] ?? EYE_COLORS.default,
    );
    root.traverse((object) => {
      if (!isMorphMesh(object)) return;
      object.frustumCulled = false;
      if (object.morphTargetDictionary && object.morphTargetInfluences) {
        meshes.push(object);
      }
      const name = object.name.toLowerCase();
      const sources = Array.isArray(object.material)
        ? object.material
        : [object.material];
      const styled = sources.map((source) => {
        const material = source.clone() as THREE.MeshStandardMaterial;
        material.clippingPlanes = [this.seatClipPlane];
        // The purchased figures already carry authored textures, so only
        // themes are hinted at through eye color on plain (texture-less)
        // materials — their albedo is never tinted wholesale.
        if (material.map) return material;
        if (material.color) {
          if (name.includes("eye")) material.color.copy(eye);
          else if (name.includes("head") || name.includes("body"))
            material.color.copy(skin);
          else if (name.includes("outfit")) material.color.multiply(outfit);
        }
        return material;
      });
      object.material = styled.length === 1 ? styled[0] : styled;
    });
  }

  /**
   * Expression is a held pose, so it is written once per state change rather
   * than every frame; the mouth is animated on top of it while speaking.
   */
  private applyExpression(character: Character): void {
    const expression = expressionForAvatarState(
      character.state,
      character.spec.config.default_expression,
    );
    const targets = EXPRESSION_TARGETS[expression];
    const strength =
      EXPRESSION_STRENGTH[character.spec.config.expression_strength];
    for (const mesh of character.meshes) {
      const dictionary = mesh.morphTargetDictionary;
      const influences = mesh.morphTargetInfluences;
      if (!dictionary || !influences) continue;
      influences.fill(0);
      for (const [name, value] of Object.entries(targets)) {
        const index = dictionary[name];
        if (index !== undefined) influences[index] = value * strength;
      }
    }
  }

  private animateCharacter(
    character: Character,
    delta: number,
    elapsed: number,
  ): void {
    const stateElapsed = (performance.now() - character.stateStartedAt) / 1000;
    const frame = avatarMotionFrame(
      this.reducedMotion ? "idle" : character.state,
      elapsed,
      stateElapsed,
      character.spec.config.motion_style,
    );

    const calm = this.reducedMotion ? 0 : this.resting ? 0.45 : 1;
    this.setRotation(
      character.torsoBone,
      character.torsoRest,
      frame.rotationX * 0.35 * calm,
      frame.rotationY * 0.5 * calm,
      frame.rotationZ * calm,
    );
    this.setRotation(
      character.neckBone,
      character.neckRest,
      frame.rotationX * 0.5 * calm,
      frame.rotationY * 0.6 * calm,
      0,
    );
    this.setRotation(
      character.headBone,
      character.headRest,
      frame.rotationX * calm,
      frame.rotationY * calm,
      frame.rotationZ * 0.6 * calm,
    );

    for (const mesh of character.meshes) {
      const dictionary = mesh.morphTargetDictionary;
      const influences = mesh.morphTargetInfluences;
      if (!dictionary || !influences) continue;
      const mouth = dictionary.mouthOpen;
      const jaw = dictionary.jawOpen;
      if (character.state === "speaking") {
        if (mouth !== undefined) influences[mouth] = frame.mouthOpen;
        if (jaw !== undefined) influences[jaw] = frame.jawOpen;
      } else {
        if (mouth !== undefined) influences[mouth] *= 0.8;
        if (jaw !== undefined) influences[jaw] *= 0.8;
      }
    }

    // Figures without morph targets still speak: rotate the jaw bone by the
    // same motion frame and settle back to its rest pose when not talking.
    if (character.jawBone && character.jawRest) {
      if (character.state === "speaking" && character.meshes.length === 0) {
        this.setRotation(
          character.jawBone,
          character.jawRest,
          frame.jawOpen * JAW_OPEN_ANGLE,
          0,
          0,
        );
      } else {
        character.jawBone.quaternion.copy(character.jawRest);
      }
    }

    character.root.position.z = THREE.MathUtils.damp(
      character.root.position.z,
      character.homeZ + character.forward,
      4.5,
      delta,
    );
  }

  private setRotation(
    bone: THREE.Object3D | null,
    rest: THREE.Quaternion | null,
    x: number,
    y: number,
    z: number,
  ): void {
    if (!bone || !rest) return;
    bone.quaternion.copy(rest);
    if (!x && !y && !z) return;
    this.offsetEuler.set(x, y, z, "XYZ");
    this.offsetQuat.setFromEuler(this.offsetEuler);
    bone.quaternion.multiply(this.offsetQuat);
  }

  private emitAnchors(now: number): void {
    if (!this.onAnchors || now - this.lastAnchorAt < ANCHOR_INTERVAL_MS) return;
    this.lastAnchorAt = now;
    const anchors: StageAnchor[] = [];
    for (const character of this.characters) {
      const bone = character.headBone ?? character.root;
      bone.getWorldPosition(this.projection);
      this.projection.y += 0.18;
      this.projection.project(this.camera);
      const nx = (this.projection.x + 1) / 2;
      anchors.push({
        id: character.spec.id,
        nx,
        x: nx * this.width,
        y: ((1 - this.projection.y) / 2) * this.height,
        visible:
          this.projection.z < 1 &&
          this.projection.x >= -1.4 &&
          this.projection.x <= 1.4,
      });
    }
    this.onAnchors(anchors);
  }

  private startLoop(): void {
    if (this.frame !== null) return;
    const step = () => {
      if (this.disposed) return;
      const delta = Math.min(this.clock.getDelta(), 0.1);
      const elapsed = (performance.now() - this.startedAt) / 1000;
      for (const character of this.characters) {
        this.animateCharacter(character, delta, elapsed);
      }
      this.renderer.render(this.scene, this.camera);
      this.emitAnchors(performance.now());
      this.frame = requestAnimationFrame(step);
    };
    this.frame = requestAnimationFrame(step);
  }

  private resize(): void {
    const parent = this.canvas.parentElement;
    const width = Math.max(
      1,
      parent?.clientWidth || this.canvas.clientWidth || 640,
    );
    const height = Math.max(
      1,
      parent?.clientHeight || this.canvas.clientHeight || 360,
    );
    if (width === this.width && height === this.height) return;
    this.width = width;
    this.height = height;
    this.camera.aspect = width / height;
    this.updateCameraFraming();
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }
}
