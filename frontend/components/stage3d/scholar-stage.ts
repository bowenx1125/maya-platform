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
  STAGE_BASE_ASSET,
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

/** How far the speaker steps out of the line, in model heights. */
const SPEAKER_STEP_FORWARD = 0.16;
const NORMALISED_HEIGHT = 1.7;
const ANCHOR_INTERVAL_MS = 60;

type MorphMesh = THREE.Mesh & {
  morphTargetDictionary?: Record<string, number>;
  morphTargetInfluences?: number[];
};

type Character = {
  spec: StageCharacter;
  root: THREE.Object3D;
  meshes: MorphMesh[];
  headBone: THREE.Object3D | null;
  neckBone: THREE.Object3D | null;
  torsoBone: THREE.Object3D | null;
  homeZ: number;
  state: AvatarState;
  stateStartedAt: number;
  forward: number;
};

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

function disposeObject(root: THREE.Object3D): void {
  const seen = new Set<THREE.Material>();
  root.traverse((object) => {
    if (!isMorphMesh(object)) return;
    object.geometry.dispose();
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
 * A canvas per Agent was the obvious shape and the wrong one: five contexts
 * mean five loops and five copies of the same mesh. The figure is loaded once
 * and cloned per speaker, so a five-Agent bench costs one download.
 *
 * There are no animation clips, and that is the trade that matters. A bench of
 * separately animated bodies could wave and sit but carried no blendshapes at
 * all, so a speaking Agent could never open its mouth. This figure carries the
 * full ARKit morph set instead, and a speech that moves the mouth reads as
 * speech from the back of a room where a gesture does not.
 */
export class ScholarStage {
  private readonly canvas: HTMLCanvasElement;
  private readonly scene: THREE.Scene;
  private readonly camera: THREE.PerspectiveCamera;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly loader = new GLTFLoader();
  private readonly draco = new DRACOLoader();
  private readonly onReady?: () => void;
  private readonly onError?: (error: Error) => void;
  private readonly onAnchors?: (anchors: StageAnchor[]) => void;

  private template: THREE.Object3D | null = null;
  private templateScale = 1;
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
    this.camera = new THREE.PerspectiveCamera(34, 1, 0.1, 60);
    this.camera.position.set(0, 1.42, 4.4);
    this.scene.add(this.camera);

    this.scene.add(new THREE.HemisphereLight(0xfff6ea, 0x4a5464, 2.1));
    const key = new THREE.DirectionalLight(0xfff3e2, 1.9);
    key.position.set(2.4, 4.2, 3.6);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xcfdcf2, 0.55);
    fill.position.set(-3, 1.4, 2);
    this.scene.add(fill);

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      alpha: true,
      antialias: true,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

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
    if (!this.template) {
      this.pending = specs;
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
      disposeObject(character.root);
    }
    this.characters.length = 0;
    if (this.template) disposeObject(this.template);
    this.template = null;
    this.draco.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }

  private load(): void {
    if (!isStageAssetUrl(STAGE_BASE_ASSET)) {
      this.onError?.(new Error("stage_asset_rejected"));
      return;
    }
    this.loader.load(
      STAGE_BASE_ASSET,
      (gltf) => {
        if (this.disposed) {
          disposeObject(gltf.scene);
          return;
        }
        const bounds = new THREE.Box3().setFromObject(gltf.scene);
        const size = bounds.getSize(new THREE.Vector3());
        this.templateScale = size.y > 0 ? NORMALISED_HEIGHT / size.y : 1;
        this.template = gltf.scene;
        if (this.pending) {
          this.rebuild(this.pending);
          this.pending = null;
        }
        this.startLoop();
        this.onReady?.();
      },
      undefined,
      (cause) => {
        if (this.disposed) return;
        this.onError?.(
          cause instanceof Error ? cause : new Error("stage_asset_failed"),
        );
      },
    );
  }

  private rebuild(specs: StageCharacter[]): void {
    for (const character of this.characters) {
      this.scene.remove(character.root);
      disposeObject(character.root);
    }
    this.characters.length = 0;
    if (!this.template) return;

    const count = Math.max(1, specs.length);
    // A gentle arc rather than a straight rank: the far speakers turn a little
    // toward the middle, which is what makes a bench read as a conversation.
    const spread = count === 1 ? 0 : Math.min(0.86, 2.5 / count);
    specs.forEach((spec, index) => {
      const root = cloneSkinned(this.template as THREE.Object3D);
      root.scale.setScalar(this.templateScale);
      const centred = index - (count - 1) / 2;
      const homeZ = -Math.abs(centred) * 0.24;
      root.position.set(centred * spread * 1.4, 0, homeZ);
      root.rotation.y = -centred * 0.17;

      const meshes: MorphMesh[] = [];
      this.styleFigure(root, spec.config, meshes);

      const character: Character = {
        spec,
        root,
        meshes,
        headBone: findBone(root, ["head"]),
        neckBone: findBone(root, ["neck"]),
        torsoBone: findBone(root, ["spine2", "spine1", "spine"]),
        homeZ,
        state: "idle",
        stateStartedAt: performance.now(),
        forward: 0,
      };
      this.applyExpression(character);
      this.scene.add(root);
      this.characters.push(character);
    });
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

    if (!this.reducedMotion) {
      // Additive on the upper body rather than on the root: rotating the whole
      // figure reads as the person swaying, not as attention moving.
      const calm = this.resting ? 0.45 : 1;
      this.addRotation(
        character.torsoBone,
        frame.rotationX * 0.35 * calm,
        frame.rotationY * 0.5 * calm,
        frame.rotationZ * calm,
      );
      this.addRotation(
        character.neckBone,
        frame.rotationX * 0.5 * calm,
        frame.rotationY * 0.6 * calm,
        0,
      );
      this.addRotation(
        character.headBone,
        frame.rotationX * calm,
        frame.rotationY * calm,
        frame.rotationZ * 0.6 * calm,
      );
    }

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

    character.root.position.z = THREE.MathUtils.damp(
      character.root.position.z,
      character.homeZ + character.forward,
      4.5,
      delta,
    );
  }

  private addRotation(
    bone: THREE.Object3D | null,
    x: number,
    y: number,
    z: number,
  ): void {
    if (!bone || (!x && !y && !z)) return;
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
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }
}
