import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { clone as cloneSkinned } from "three/examples/jsm/utils/SkeletonUtils.js";

import type { AvatarConfig, AvatarState } from "../avatar";
import {
  STAGE_BASE_ASSET,
  STAGE_CLIP_ASSETS,
  isStageAssetUrl,
  type StageClipName,
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

/**
 * Robe tints, so five copies of one mesh read as five different speakers.
 *
 * The platform avatar themes name skin colours for a head-only crop. Here the
 * same four themes tint the whole figure instead, because the body is what a
 * classroom actually sees from the back row.
 */
const ROBE_TINTS: Record<AvatarConfig["material_theme"], number> = {
  demo: 0xffffff,
  warm_sand: 0xe7c9a6,
  cool_slate: 0xb9c6d4,
  civic_olive: 0xc3bd93,
};

/** How far the speaker steps out of the line, in model heights. */
const SPEAKER_STEP_FORWARD = 0.16;
const NORMALISED_HEIGHT = 1.7;
const ANCHOR_INTERVAL_MS = 60;

type MicroMode = "rest" | "listening" | "thinking" | "speaking" | "waving";

type Character = {
  spec: StageCharacter;
  root: THREE.Object3D;
  mixer: THREE.AnimationMixer;
  actions: Map<string, THREE.AnimationAction>;
  current: THREE.AnimationAction | null;
  currentName: string;
  headBone: THREE.Object3D | null;
  neckBone: THREE.Object3D | null;
  torsoBone: THREE.Object3D | null;
  homeX: number;
  homeZ: number;
  micro: MicroMode;
  microBlend: Record<MicroMode, number>;
  stateStartedAt: number;
  forward: number;
};

const MICRO_MODES: MicroMode[] = [
  "rest",
  "listening",
  "thinking",
  "speaking",
  "waving",
];

function findBone(
  root: THREE.Object3D,
  names: string[],
): THREE.Object3D | null {
  let found: THREE.Object3D | null = null;
  root.traverse((object) => {
    if (found) return;
    const name = object.name.toLowerCase();
    if (names.some((candidate) => name === candidate)) found = object;
  });
  return found;
}

function disposeObject(root: THREE.Object3D): void {
  const seen = new Set<THREE.Material>();
  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if (!mesh.isMesh) return;
    mesh.geometry.dispose();
    const materials = Array.isArray(mesh.material)
      ? mesh.material
      : [mesh.material];
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
 * mean five loops and five copies of an 11 MB skinned mesh. The mesh is loaded
 * once and cloned per speaker, so a five-Agent stage costs one download.
 */
export class ScholarStage {
  private readonly canvas: HTMLCanvasElement;
  private readonly scene: THREE.Scene;
  private readonly camera: THREE.PerspectiveCamera;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly loader = new GLTFLoader();
  private readonly onReady?: () => void;
  private readonly onError?: (error: Error) => void;
  private readonly onAnchors?: (anchors: StageAnchor[]) => void;

  private template: THREE.Object3D | null = null;
  private templateScale = 1;
  private readonly clips = new Map<string, THREE.AnimationClip>();
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
    this.camera.position.set(0, 1.45, 4.5);
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

    window.addEventListener("resize", this.resizeHandler, { passive: true });
    this.resize();
    void this.load();
  }

  setCharacters(specs: StageCharacter[]): void {
    if (!this.template) {
      this.pending = specs;
      return;
    }
    this.rebuild(specs);
  }

  /** Before Start, and after the debate ends, the whole bench sits. */
  setResting(resting: boolean): void {
    if (this.resting === resting) return;
    this.resting = resting;
    for (const character of this.characters) {
      this.applyAction(character, character.currentName, true);
    }
  }

  setVisual(id: string, state: AvatarState): void {
    const character = this.characters.find((item) => item.spec.id === id);
    if (!character) return;
    const action = this.actionForState(state);
    const micro = this.microForState(state);
    if (character.currentName !== action) this.applyAction(character, action);
    if (character.micro !== micro) {
      character.micro = micro;
      character.stateStartedAt = performance.now();
    }
    character.forward = state === "speaking" ? SPEAKER_STEP_FORWARD : 0;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    this.frame = null;
    window.removeEventListener("resize", this.resizeHandler);
    for (const character of this.characters) {
      character.mixer.stopAllAction();
      this.scene.remove(character.root);
      disposeObject(character.root);
    }
    this.characters.length = 0;
    if (this.template) disposeObject(this.template);
    this.template = null;
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }

  private actionForState(state: AvatarState): string {
    if (this.resting) return "sit";
    if (state === "speaking") return "talk";
    return "idle";
  }

  private microForState(state: AvatarState): MicroMode {
    switch (state) {
      case "speaking":
        return "speaking";
      case "thinking":
        return "thinking";
      case "listening":
        return "listening";
      case "nod_yes":
        return "waving";
      default:
        return "rest";
    }
  }

  private async load(): Promise<void> {
    try {
      if (!isStageAssetUrl(STAGE_BASE_ASSET)) {
        throw new Error("stage_asset_rejected");
      }
      const base = await this.loader.loadAsync(STAGE_BASE_ASSET);
      if (this.disposed) {
        disposeObject(base.scene);
        return;
      }

      const bounds = new THREE.Box3().setFromObject(base.scene);
      const size = bounds.getSize(new THREE.Vector3());
      this.templateScale = size.y > 0 ? NORMALISED_HEIGHT / size.y : 1;
      this.template = base.scene;
      for (const clip of base.animations) this.clips.set("idle", clip);

      if (this.pending) {
        this.rebuild(this.pending);
        this.pending = null;
      }
      this.startLoop();
      this.onReady?.();

      // The extra clips are small and never block the first frame: the bench
      // is already standing and breathing while they arrive.
      await Promise.allSettled(
        (Object.keys(STAGE_CLIP_ASSETS) as StageClipName[]).map(
          async (name) => {
            const url = STAGE_CLIP_ASSETS[name];
            if (!isStageAssetUrl(url)) return;
            const gltf = await this.loader.loadAsync(url);
            const clip = gltf.animations[0];
            if (!clip || this.disposed) return;
            this.clips.set(name, clip);
            for (const character of this.characters)
              this.bindClip(character, name, clip);
          },
        ),
      );

      if (this.resting) {
        for (const character of this.characters)
          this.applyAction(character, "sit", true);
      }
    } catch (cause) {
      if (this.disposed) return;
      this.onError?.(
        cause instanceof Error ? cause : new Error("stage_asset_failed"),
      );
    }
  }

  private bindClip(
    character: Character,
    name: string,
    clip: THREE.AnimationClip,
  ): void {
    if (character.actions.has(name)) return;
    character.actions.set(
      name,
      character.mixer.clipAction(clip, character.root),
    );
  }

  private rebuild(specs: StageCharacter[]): void {
    for (const character of this.characters) {
      character.mixer.stopAllAction();
      this.scene.remove(character.root);
      disposeObject(character.root);
    }
    this.characters.length = 0;
    if (!this.template) return;

    const count = Math.max(1, specs.length);
    // A gentle arc rather than a straight rank: the far speakers turn a little
    // toward the middle, which is what makes a bench read as a conversation.
    const spread = count === 1 ? 0 : Math.min(0.82, 2.4 / count);
    specs.forEach((spec, index) => {
      const root = cloneSkinned(this.template as THREE.Object3D);
      root.scale.setScalar(this.templateScale);
      const centred = index - (count - 1) / 2;
      const homeX = centred * spread * 1.35;
      const homeZ = -Math.abs(centred) * 0.22;
      root.position.set(homeX, 0, homeZ);
      root.rotation.y = -centred * 0.16;

      const tint = new THREE.Color(
        ROBE_TINTS[spec.config.material_theme] ?? ROBE_TINTS.demo,
      );
      root.traverse((object) => {
        const mesh = object as THREE.Mesh;
        if (!mesh.isMesh) return;
        mesh.frustumCulled = false;
        const materials = Array.isArray(mesh.material)
          ? mesh.material
          : [mesh.material];
        mesh.material = materials.map((source) => {
          const material = source.clone() as THREE.MeshStandardMaterial;
          if (material.color) material.color.multiply(tint);
          return material;
        });
        if (!Array.isArray(mesh.material)) return;
        if (mesh.material.length === 1) mesh.material = mesh.material[0];
      });

      const mixer = new THREE.AnimationMixer(root);
      const character: Character = {
        spec,
        root,
        mixer,
        actions: new Map(),
        current: null,
        currentName: "",
        headBone: findBone(root, ["head"]),
        neckBone: findBone(root, ["neck"]),
        torsoBone: findBone(root, ["spine02", "spine01", "spine"]),
        homeX,
        homeZ,
        micro: "rest",
        microBlend: {
          rest: 1,
          listening: 0,
          thinking: 0,
          speaking: 0,
          waving: 0,
        },
        stateStartedAt: performance.now(),
        forward: 0,
      };
      for (const [name, clip] of this.clips)
        this.bindClip(character, name, clip);
      this.applyAction(character, this.resting ? "sit" : "idle", true);
      this.scene.add(root);
      this.characters.push(character);
    });
  }

  private applyAction(
    character: Character,
    name: string,
    immediate = false,
  ): void {
    const resolved =
      this.resting && character.actions.has("sit") ? "sit" : name;
    const next =
      character.actions.get(resolved) ?? character.actions.get("idle");
    if (!next) return;
    character.currentName = resolved;
    if (next === character.current) return;
    next.reset();
    next.enabled = true;
    next.setLoop(THREE.LoopRepeat, Infinity);
    next.setEffectiveWeight(1);
    next.play();
    if (character.current && !immediate) {
      next.crossFadeFrom(character.current, 0.42, false);
    } else if (character.current) {
      character.current.stop();
    }
    character.current = next;
  }

  /**
   * Additive bone motion on top of whichever clip is running.
   *
   * These meshes carry no blendshapes, so a speaking Agent cannot open its
   * mouth. The head and torso do the work the mouth would: a nod on the beat
   * while speaking, a tilt while thinking, a turn toward the speaker while
   * listening.
   */
  private applyMicroMotion(
    character: Character,
    delta: number,
    elapsed: number,
  ): void {
    if (this.reducedMotion) return;
    const stateElapsed = (performance.now() - character.stateStartedAt) / 1000;
    for (const mode of MICRO_MODES) {
      character.microBlend[mode] = THREE.MathUtils.damp(
        character.microBlend[mode],
        character.micro === mode ? 1 : 0,
        5.2,
        delta,
      );
    }

    const breathe = Math.sin(elapsed * 0.9);
    const drift = Math.sin(elapsed * 0.47 + 1.1);
    const talkNod = Math.sin(elapsed * 2.9);
    const talkTurn = Math.sin(elapsed * 1.4 + 0.5);
    const thinkTilt = Math.sin(elapsed * 0.85 + 0.4);
    const blend = character.microBlend;

    if (character.torsoBone) {
      this.addRotation(
        character.torsoBone,
        breathe * 0.012 * (blend.rest + blend.listening),
        drift * 0.02 * blend.rest,
        thinkTilt * 0.02 * blend.thinking,
      );
    }
    if (character.neckBone) {
      this.addRotation(
        character.neckBone,
        talkNod * 0.03 * blend.speaking,
        talkTurn * 0.035 * blend.speaking - 0.06 * blend.thinking,
        -0.05 * blend.thinking,
      );
    }
    if (character.headBone) {
      const nodEnvelope = Math.max(0, 1 - stateElapsed / 1.3);
      this.addRotation(
        character.headBone,
        talkNod * 0.045 * blend.speaking +
          Math.sin(stateElapsed * 10.5) * 0.09 * blend.waving * nodEnvelope,
        drift * 0.03 * blend.listening,
        thinkTilt * 0.03 * blend.thinking,
      );
    }
  }

  private addRotation(
    bone: THREE.Object3D,
    x: number,
    y: number,
    z: number,
  ): void {
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
      this.projection.y += 0.22;
      this.projection.project(this.camera);
      const inside =
        this.projection.z < 1 &&
        this.projection.x >= -1.4 &&
        this.projection.x <= 1.4;
      const nx = (this.projection.x + 1) / 2;
      anchors.push({
        id: character.spec.id,
        nx,
        x: nx * this.width,
        y: ((1 - this.projection.y) / 2) * this.height,
        visible: inside,
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
        character.mixer.update(delta);
        this.applyMicroMotion(character, delta, elapsed);
        character.root.position.z = THREE.MathUtils.damp(
          character.root.position.z,
          character.homeZ + character.forward,
          4.5,
          delta,
        );
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
