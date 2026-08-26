import * as THREE from "three";
import { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import {
  AVATAR_ASSET_URL,
  AVATAR_DECODER_PATH,
  type AvatarConfig,
  type AvatarExpression,
  type AvatarState,
} from "./types";
import { avatarMotionFrame, expressionForAvatarState } from "./avatar-motion";

export type AvatarRendererOptions = {
  canvas: HTMLCanvasElement;
  assetUrl?: string;
  decoderPath?: string;
  onReady?: () => void;
  onError?: (error: Error) => void;
};

type MorphTargetMesh = THREE.Mesh & {
  morphTargetDictionary?: Record<string, number>;
  morphTargetInfluences?: number[];
};

type RenderableMaterial = THREE.Material & {
  color?: THREE.Color;
  roughness?: number;
  metalness?: number;
};

const SKIN_COLORS: Record<AvatarConfig["material_theme"], string> = {
  demo: "#d5a27c",
  warm_sand: "#c88b68",
  cool_slate: "#a9b9c9",
  civic_olive: "#a49a75",
};

const EYE_COLORS: Record<
  Exclude<NonNullable<AvatarConfig["eye_color"]>, "default"> | "default",
  string
> = {
  default: "#72523e",
  brown: "#5b3726",
  hazel: "#8a6a3e",
  blue: "#5d86b2",
  green: "#5b8968",
  gray: "#7e8790",
};

const EXPRESSION_TARGETS: Record<AvatarExpression, Record<string, number>> = {
  neutral: {},
  attentive: { browInnerUp: 0.5, eyeWideLeft: 0.35, eyeWideRight: 0.35 },
  happy: { mouthSmile: 0.75, mouthSmileLeft: 0.55, mouthSmileRight: 0.55 },
  serious_angry: { browDownLeft: 0.55, browDownRight: 0.55, mouthPress: 0.25 },
  sad: { mouthFrownLeft: 0.55, mouthFrownRight: 0.55, browInnerUp: 0.3 },
};

const EXPRESSION_STRENGTH: Record<AvatarConfig["expression_strength"], number> =
  {
    low: 0.35,
    medium: 0.65,
    high: 1,
  };

function safeLocalAssetUrl(candidate: string | undefined): string {
  if (!candidate) return AVATAR_ASSET_URL;
  if (candidate.startsWith("/avatars/") && !candidate.includes(".."))
    return candidate;
  return AVATAR_ASSET_URL;
}

function isMesh(object: THREE.Object3D): object is MorphTargetMesh {
  return Boolean((object as MorphTargetMesh).isMesh);
}

function shouldKeepForHeadCrop(object: THREE.Object3D): boolean {
  const name = object.name.toLowerCase();
  if (!name) return false;
  return ["head", "eye", "teeth", "hair", "glass", "neck", "face"].some(
    (part) => name.includes(part),
  );
}

function disposeMaterial(material: RenderableMaterial): void {
  const textureNames = [
    "map",
    "alphaMap",
    "aoMap",
    "bumpMap",
    "displacementMap",
    "emissiveMap",
    "metalnessMap",
    "normalMap",
    "roughnessMap",
  ] as const;
  for (const textureName of textureNames) {
    const texture = material[textureName as keyof RenderableMaterial];
    if (texture instanceof THREE.Texture) texture.dispose();
  }
  material.dispose();
}

function disposeObject(root: THREE.Object3D): void {
  const disposedMaterials = new Set<THREE.Material>();
  root.traverse((object) => {
    if (!isMesh(object)) return;
    object.geometry.dispose();
    const materials = Array.isArray(object.material)
      ? object.material
      : [object.material];
    for (const material of materials) {
      if (disposedMaterials.has(material)) continue;
      disposedMaterials.add(material);
      disposeMaterial(material as RenderableMaterial);
    }
  });
}

/**
 * A small presentation adapter: the platform owns state/config, while this
 * class owns only Three.js resources and the animation loop.
 */
export class AvatarRenderer {
  private readonly canvas: HTMLCanvasElement;
  private readonly scene: THREE.Scene;
  private readonly camera: THREE.PerspectiveCamera;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly loader: GLTFLoader;
  private readonly draco: DRACOLoader;
  private readonly onReady?: () => void;
  private readonly onError?: (error: Error) => void;
  private root: THREE.Object3D | null = null;
  private config: AvatarConfig | null = null;
  private state: AvatarState = "idle";
  private animationFrame: number | null = null;
  private startedAt = performance.now();
  private stateStartedAt = this.startedAt;
  private disposed = false;
  private width = 0;
  private height = 0;
  private readonly resizeHandler = () => this.resize();

  constructor(options: AvatarRendererOptions) {
    this.canvas = options.canvas;
    this.onReady = options.onReady;
    this.onError = options.onError;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(24, 1, 0.01, 20);
    this.camera.position.set(0, 0.02, 0.72);
    this.scene.add(this.camera);

    this.scene.add(new THREE.HemisphereLight(0xfff4e8, 0x3b536c, 1.8));
    const keyLight = new THREE.DirectionalLight(0xffffff, 2.1);
    keyLight.position.set(0.6, 1.2, 1.2);
    this.scene.add(keyLight);
    const fillLight = new THREE.DirectionalLight(0xbed6ff, 0.7);
    fillLight.position.set(-1, 0.3, 0.6);
    this.scene.add(fillLight);

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      alpha: true,
      antialias: true,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.setAnimationLoop(null);

    this.draco = new DRACOLoader();
    this.draco.setDecoderPath(options.decoderPath ?? AVATAR_DECODER_PATH);
    this.loader = new GLTFLoader();
    this.loader.setDRACOLoader(this.draco);
    window.addEventListener("resize", this.resizeHandler, { passive: true });
    this.resize();
    this.load(safeLocalAssetUrl(options.assetUrl));
  }

  setConfig(config: AvatarConfig): void {
    this.config = config;
    if (this.root) {
      this.applyConfig(this.root, config);
      this.applyExpression(this.root, this.expressionForState());
    }
  }

  setState(state: AvatarState): void {
    if (state === this.state) return;
    this.state = state;
    this.stateStartedAt = performance.now();
    if (this.root) this.applyExpression(this.root, this.expressionForState());
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.animationFrame !== null) {
      cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
    }
    window.removeEventListener("resize", this.resizeHandler);
    if (this.root) {
      this.scene.remove(this.root);
      disposeObject(this.root);
      this.root = null;
    }
    this.draco.dispose();
    this.renderer.setAnimationLoop(null);
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }

  private load(assetUrl: string): void {
    this.loader.load(
      assetUrl,
      (gltf) => {
        if (this.disposed) {
          disposeObject(gltf.scene);
          return;
        }
        this.root = this.prepareHeadCrop(gltf.scene);
        this.scene.add(this.root);
        if (this.config) this.applyConfig(this.root, this.config);
        this.applyExpression(this.root, this.expressionForState());
        this.startedAt = performance.now();
        this.stateStartedAt = this.startedAt;
        this.startLoop();
        this.onReady?.();
      },
      undefined,
      (cause) => {
        if (this.disposed) return;
        const error =
          cause instanceof Error ? cause : new Error("avatar_asset_failed");
        this.onError?.(error);
      },
    );
  }

  private prepareHeadCrop(scene: THREE.Object3D): THREE.Object3D {
    scene.traverse((object) => {
      if (object === scene) return;
      if (object.children.length === 0 && !shouldKeepForHeadCrop(object)) {
        object.visible = false;
      }
    });
    const bounds = new THREE.Box3();
    scene.traverse((object) => {
      if (isMesh(object) && object.visible) bounds.expandByObject(object);
    });
    if (bounds.isEmpty()) return scene;
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    scene.position.sub(center);
    scene.position.y += Math.max(size.y * 0.04, 0.015);
    this.camera.position.z = Math.max(0.62, Math.min(1.15, size.y * 1.5));
    this.camera.lookAt(0, 0, 0);
    return scene;
  }

  private applyConfig(root: THREE.Object3D, config: AvatarConfig): void {
    const skinColor = new THREE.Color(
      SKIN_COLORS[config.material_theme] ?? SKIN_COLORS.demo,
    );
    const eyeColor = new THREE.Color(
      EYE_COLORS[config.eye_color ?? "default"] ?? EYE_COLORS.default,
    );
    root.traverse((object) => {
      if (!isMesh(object)) return;
      const meshName = object.name.toLowerCase();
      const materials = Array.isArray(object.material)
        ? object.material
        : [object.material];
      object.material = materials.map((source) => {
        const candidate = source as RenderableMaterial;
        const material = candidate.userData.mayaAvatarMaterial
          ? candidate
          : (source.clone() as RenderableMaterial);
        material.userData.mayaAvatarMaterial = true;
        if (meshName.includes("eye")) {
          material.color?.copy(eyeColor);
          if (material.roughness !== undefined) material.roughness = 0.25;
        } else if (meshName.includes("head") || meshName.includes("neck")) {
          material.color?.copy(skinColor);
          if (material.roughness !== undefined) material.roughness = 0.62;
        }
        return material;
      });
    });
  }

  private expressionForState(): AvatarExpression {
    return expressionForAvatarState(
      this.state,
      this.config?.default_expression ?? "neutral",
    );
  }

  private applyExpression(
    root: THREE.Object3D,
    expression: AvatarExpression,
  ): void {
    const values = EXPRESSION_TARGETS[expression];
    const strength =
      EXPRESSION_STRENGTH[this.config?.expression_strength ?? "medium"];
    root.traverse((object) => {
      if (
        !isMesh(object) ||
        !object.morphTargetDictionary ||
        !object.morphTargetInfluences
      ) {
        return;
      }
      object.morphTargetInfluences.fill(0);
      for (const [targetName, value] of Object.entries(values)) {
        const index = object.morphTargetDictionary[targetName];
        if (index !== undefined)
          object.morphTargetInfluences[index] = value * strength;
      }
    });
  }

  private animate(elapsed: number): void {
    if (!this.root) return;
    const activeRoot = this.root;
    const frame = avatarMotionFrame(
      this.state,
      elapsed,
      (performance.now() - this.stateStartedAt) / 1000,
      this.config?.motion_style ?? "calm",
    );
    activeRoot.rotation.x = frame.rotationX;
    activeRoot.rotation.y = frame.rotationY;
    activeRoot.rotation.z = frame.rotationZ;
    this.animateMorphTargets(activeRoot, frame);
  }

  private animateMorphTargets(
    root: THREE.Object3D,
    frame: ReturnType<typeof avatarMotionFrame>,
  ): void {
    root.traverse((object) => {
      if (
        !isMesh(object) ||
        !object.morphTargetDictionary ||
        !object.morphTargetInfluences
      ) {
        return;
      }
      const mouthOpen = object.morphTargetDictionary.mouthOpen;
      const jawOpen = object.morphTargetDictionary.jawOpen;
      if (this.state === "speaking") {
        if (mouthOpen !== undefined)
          object.morphTargetInfluences[mouthOpen] = frame.mouthOpen;
        if (jawOpen !== undefined)
          object.morphTargetInfluences[jawOpen] = frame.jawOpen;
      } else {
        if (mouthOpen !== undefined)
          object.morphTargetInfluences[mouthOpen] *= 0.8;
        if (jawOpen !== undefined) object.morphTargetInfluences[jawOpen] *= 0.8;
      }
    });
  }

  private startLoop(): void {
    if (this.animationFrame !== null) return;
    const frame = () => {
      if (this.disposed) return;
      const elapsed = (performance.now() - this.startedAt) / 1000;
      this.animate(elapsed);
      this.renderer.render(this.scene, this.camera);
      this.animationFrame = requestAnimationFrame(frame);
    };
    this.animationFrame = requestAnimationFrame(frame);
  }

  private resize(): void {
    const parent = this.canvas.parentElement;
    const width = Math.max(
      1,
      parent?.clientWidth || this.canvas.clientWidth || 320,
    );
    const height = Math.max(
      1,
      parent?.clientHeight || this.canvas.clientHeight || width,
    );
    if (width === this.width && height === this.height) return;
    this.width = width;
    this.height = height;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }
}
