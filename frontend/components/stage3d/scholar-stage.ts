import {
  eggCrownWorldPosition,
  prepareEggModel,
  type EggModel,
} from "./egg-model";

import type { SparkRenderer, SplatMesh } from "@sparkjsdev/spark";
import * as THREE from "three";
import { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { clone as cloneSkinned } from "three/examples/jsm/utils/SkeletonUtils.js";

import {
  applyRelaxedStandingPose,
  avatarMotionFrame,
  expressionForAvatarState,
  hangProfileForAsset,
  type AvatarConfig,
  type AvatarExpression,
  type AvatarState,
} from "../avatar";
import {
  STAGE_CHARACTER_ASSETS,
  STAGE_DECODER_PATH,
  isStageAssetUrl,
} from "./assets";
import {
  stageCameraPositionBlocked,
  STAGE_STANDING_RADIUS,
  standingPlacement,
  type StageSlot,
} from "./placement";
import {
  requestedStageScenePack,
  stageScenePack,
  type StageScenePack,
} from "./scene-packs";
import type {
  ArmStep,
  BoneOffset,
  PerformancePlayer,
  PerformanceSample,
} from "./performance-player";

export type StageCharacter = {
  id: string;
  slot: StageSlot;
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

const NORMALISED_HEIGHT = 1.7;
const SPLAT_CHARACTER_HEIGHT = 1.68;
const ANCHOR_INTERVAL_MS = 60;
const CAMERA_FOV_DEGREES = 34;
const DEFAULT_CAMERA_Z = 5.0;
const CAMERA_HEIGHT = 1.78;
const CAMERA_TARGET = new THREE.Vector3(0, 0.74, 0.2);
const CAMERA_DEPTH_MARGIN = 0.35;
const CAMERA_EDGE_MARGIN = 1.08;

/** Standing-ring center for the non-splat stage (seats / floor framing). */
const STAGE_CENTER_Z = 0.2;
const SPLAT_STAGE_CENTER_Z = 1.15;
const FLOOR_Y = -0.42;
const FLOOR_COLLIDER_WIDTH = 7.2;
const FLOOR_COLLIDER_DEPTH = 6.4;
const FLOOR_COLLIDER_THICKNESS = 0.08;
/** Jaw opening angle while a character is speaking, in radians. */
const JAW_OPEN_ANGLE = 0.28;

/**
 * A full-panorama Gaussian scene used to prove real world-space camera
 * motion. The ignored local asset is replaceable without changing navigation.
 */
const SPLAT_CAMERA_FOV_DEGREES = 58;
const SPLAT_CAMERA_FAR = 160;
const SPLAT_PANORAMA_RADIUS = 150;
const SPLAT_DEPTH_MAX = 40;
const SPLAT_SHELL_SEGMENTS_X = 256;
const SPLAT_SHELL_SEGMENTS_Y = 128;

const FIRST_PERSON_EYE_Y = FLOOR_Y + 1.6;
const SPLAT_CAPTURE_ORIGIN = new THREE.Vector3(0, FIRST_PERSON_EYE_Y, -5.4);
const FIRST_PERSON_START = SPLAT_CAPTURE_ORIGIN.clone();
const FIRST_PERSON_YAW = 0;
const FIRST_PERSON_PITCH = THREE.MathUtils.degToRad(-4);
const STAGE_CAMERA_MOVE_SPEED = 1.65;
const STAGE_CAMERA_TURN_SPEED = THREE.MathUtils.degToRad(90);
const STAGE_CAMERA_NUDGE = 0.22;
const STAGE_CAMERA_TURN_NUDGE = THREE.MathUtils.degToRad(7.5);
const STAGE_CAMERA_MOUSE_SENSITIVITY = 0.0022;
const STAGE_CAMERA_PITCH_LIMIT = THREE.MathUtils.degToRad(55);
const OVERVIEW_POSITION = new THREE.Vector3(0, 2.25, -6.2);
const OVERVIEW_TARGET = new THREE.Vector3(0, 0.48, SPLAT_STAGE_CENTER_Z);
const OVERVIEW_TRANSITION_SECONDS = 1.55;
const MIN_RENDER_PIXEL_RATIO = 0.75;
const MAX_RENDER_PIXEL_RATIO = 1.5;
const SLOW_FRAME_SECONDS = 1 / 27;
const SLOW_FRAME_THRESHOLD = 100;

/**
 * Opt-in depth-mesh backdrop: the same courtyard front view as the splat
 * trial, as a sharp color image plus a matching depth map (dark near, bright
 * far). The vertex shader re-projects the source pixels with these camera
 * constants, so the fixed front view reproduces the original composition.
 */
const STAGE_DEPTH_COLOR_URL = "/stage/courtyard-depth-color.png";
const STAGE_DEPTH_MAP_URL = "/stage/courtyard-depth-map.png";
const DEPTH_CAMERA_FOV_DEGREES = 56.35;
const DEPTH_SOURCE_ASPECT = 1448 / 1086;
/** Artist-chosen remap of the depth ramp onto view-space distances. */
const DEPTH_NEAR = 1;
const DEPTH_FAR = 5;
const DEPTH_CAMERA_FAR = 10;
const DEPTH_MESH_SEGMENTS_X = 200;
const DEPTH_MESH_SEGMENTS_Y = 150;
/** Plane overscan, so parallax shifts never expose the mesh border. */
const DEPTH_EDGE_BLEED = 1.05;
/** Parallax amplitude as a fraction of the remapped depth range. */
const DEPTH_PARALLAX_SCALE = 0.004;
export type StageCameraCommand =
  "forward" | "backward" | "left" | "right" | "turn-left" | "turn-right";

/** Positive yaw looks left in the stage's +Z-forward coordinate system. */
export function stageCameraTurnSign(command: StageCameraCommand): -1 | 0 | 1 {
  if (command === "turn-left") return 1;
  if (command === "turn-right") return -1;
  return 0;
}

/** Root yaw that faces the default stage camera (+Z). */
export const STAGE_FRONT_YAW = 0;
const STAGE_FRONT_YAW_EPS = THREE.MathUtils.degToRad(1);
/** Speaking / restore body-yaw smoothing (higher = snappier). */
const SPEAK_YAW_LAMBDA = 6;

/** True when the seat rest pose already faces the camera/front. */
export function stageSeatFacesFront(seatYaw: number): boolean {
  const delta = Math.atan2(
    Math.sin(seatYaw - STAGE_FRONT_YAW),
    Math.cos(seatYaw - STAGE_FRONT_YAW),
  );
  return Math.abs(delta) < STAGE_FRONT_YAW_EPS;
}

/** Body yaw while idle (seat) or speaking (front, unless already front). */
export function stageBodyYawTarget(seatYaw: number, speaking: boolean): number {
  if (!speaking || stageSeatFacesFront(seatYaw)) return seatYaw;
  return STAGE_FRONT_YAW;
}

function shortestYawDelta(from: number, to: number): number {
  return Math.atan2(Math.sin(to - from), Math.cos(to - from));
}

export function stageSplatCameraFov(aspect: number): number {
  const blend = THREE.MathUtils.clamp((aspect - 0.5) / 0.4, 0, 1);
  return THREE.MathUtils.lerp(72, SPLAT_CAMERA_FOV_DEGREES, blend);
}

type MorphMesh = THREE.Mesh & {
  morphTargetDictionary?: Record<string, number>;
  morphTargetInfluences?: number[];
};

type Character = {
  egg: EggModel | null;
  spec: StageCharacter;
  root: THREE.Object3D;
  shadow: THREE.Mesh;
  meshes: MorphMesh[];
  headBone: THREE.Object3D | null;
  headRest: THREE.Quaternion | null;
  neckBone: THREE.Object3D | null;
  neckRest: THREE.Quaternion | null;
  torsoBone: THREE.Object3D | null;
  torsoRest: THREE.Quaternion | null;
  upperArmLBone: THREE.Object3D | null;
  upperArmLRest: THREE.Quaternion | null;
  upperArmRBone: THREE.Object3D | null;
  upperArmRRest: THREE.Quaternion | null;
  forearmLBone: THREE.Object3D | null;
  forearmLRest: THREE.Quaternion | null;
  forearmRBone: THREE.Object3D | null;
  forearmRRest: THREE.Quaternion | null;
  handLBone: THREE.Object3D | null;
  handLRest: THREE.Quaternion | null;
  handRBone: THREE.Object3D | null;
  handRRest: THREE.Quaternion | null;
  /**
   * Parent-chain rest orientation per arm bone, in the figure's own frame
   * (root yaw removed). The player emits figure-space rotation steps; the
   * stage converts them to bone-local quaternions against these captures, so
   * one clip works across rig families with differently oriented bones.
   */
  upperArmLParentRest: THREE.Quaternion | null;
  upperArmRParentRest: THREE.Quaternion | null;
  forearmLParentRest: THREE.Quaternion | null;
  forearmRParentRest: THREE.Quaternion | null;
  handLParentRest: THREE.Quaternion | null;
  handRParentRest: THREE.Quaternion | null;
  jawBone: THREE.Object3D | null;
  jawRest: THREE.Quaternion | null;
  hasSpeechMorph: boolean;
  /** Authored standing yaw to restore when idle. */
  seatYaw: number;
  state: AvatarState;
  stateStartedAt: number;
  /** Compiled turn timeline, when the TTS provider returned word timestamps. */
  performance: CharacterPerformance | null;
};

/**
 * The timeline advances with the render loop between coarse audio-element
 * timeupdates; syncTime carries the latest authoritative audio position.
 */
type CharacterPerformance = {
  player: PerformancePlayer;
  time: number;
  syncTime: number | null;
};

/**
 * Bone naming differs per rig family the stage has loaded: the elder figure
 * uses UE-style names (spine_02, neck_01), the noble an AdvancedSkeleton rig
 * (Chest_M, Neck_M), and RPM/Mixamo figures Hips-style names (Spine1, Neck).
 * The single-name lookup below only ever matched the head, so neck and torso
 * clips silently did nothing and all motion concentrated in the head — which
 * is what pushed collars and hair through the mesh. Aliases resolve per
 * family, most specific first.
 */
const BONE_ALIASES = {
  head: [/^head$/i, /^head_m$/i, /^mixamorig:?head$/i],
  neck: [/^neck_?01$/i, /^neck$/i, /^neck_m$/i, /^mixamorig:?neck$/i],
  torso: [
    /^chest_m$/i,
    /^spine2$/i,
    /^spine_?02$/i,
    /^mixamorig:?spine2$/i,
    /^spine1_?m$/i,
    /^spine1$/i,
    /^mixamorig:?spine1$/i,
    /^spine$/i,
  ],
  jaw: [/^bone_jaw$/i, /^jawjoint_m$/i, /^mixamorig:?jaw$/i],
  // Arm chains only exist on the rigged Mixamo figures; the legacy purchased
  // pair has no matching bones, so these channels simply never resolve there
  // and its figures keep the head-only choreography.
  upperArmL: [
    /^mixamorig:?leftarm$/i,
    /^upperarm_l$/i,
    /^leftarm$/i,
    /^shoulder_?l$/i,
  ],
  upperArmR: [
    /^mixamorig:?rightarm$/i,
    /^upperarm_r$/i,
    /^rightarm$/i,
    /^shoulder_?r$/i,
  ],
  forearmL: [
    /^mixamorig:?leftforearm$/i,
    /^lowerarm_l$/i,
    /^leftforearm$/i,
    /^elbow_?l$/i,
  ],
  forearmR: [
    /^mixamorig:?rightforearm$/i,
    /^lowerarm_r$/i,
    /^rightforearm$/i,
    /^elbow_?r$/i,
  ],
  handL: [/^mixamorig:?lefthand$/i, /^hand_?l$/i, /^lefthand$/i],
  handR: [/^mixamorig:?righthand$/i, /^hand_?r$/i, /^righthand$/i],
} as const;

type StageBone = keyof typeof BONE_ALIASES;

export function findBone(
  root: THREE.Object3D,
  bone: StageBone,
): THREE.Object3D | null {
  for (const pattern of BONE_ALIASES[bone]) {
    let found: THREE.Object3D | null = null;
    root.traverse((object) => {
      if (found) return;
      if (pattern.test(object.name)) found = object;
    });
    if (found) return found;
  }
  return null;
}

function isMorphMesh(object: THREE.Object3D): object is MorphMesh {
  return Boolean((object as MorphMesh).isMesh);
}

/**
 * Which opt-in backdrop the URL asks for, if any. depth wins over splat so
 * the heavier Spark/SOG download never starts when both flags are present.
 */
export type StageBackdropMode = "depth" | "splat" | null;

export function stageBackdropMode(): StageBackdropMode {
  if (typeof window === "undefined") return null;
  const search = new URLSearchParams(window.location.search);
  if (search.get("depth") === "1") return "depth";
  if (search.get("splat") === "1") return "splat";
  return null;
}

/** The splat backdrop is opt-in: only ?splat=1 ever starts the download. */
export function splatBackdropRequested(): boolean {
  return stageBackdropMode() === "splat";
}

/** The depth-mesh backdrop is opt-in: only ?depth=1 ever loads its textures. */
export function depthBackdropRequested(): boolean {
  return stageBackdropMode() === "depth";
}

/**
 * Both backdrops are cover-fit: their source aspect is narrower than most
 * viewports, so on wide canvases the vertical FOV is pulled in (zoom in) while
 * the full width still fills the frame — the same behavior CSS `cover` gives
 * the static background image they replace.
 */
function backdropCameraFov(
  aspect: number,
  sourceFovDegrees: number,
  sourceAspect: number,
): number {
  if (aspect >= sourceAspect) {
    const halfWidth =
      Math.tan(THREE.MathUtils.degToRad(sourceFovDegrees / 2)) * sourceAspect;
    return THREE.MathUtils.radToDeg(
      2 * Math.atan(halfWidth / Math.max(aspect, 0.01)),
    );
  }
  return sourceFovDegrees;
}

function depthCameraFov(aspect: number): number {
  return backdropCameraFov(
    aspect,
    DEPTH_CAMERA_FOV_DEGREES,
    DEPTH_SOURCE_ASPECT,
  );
}

/**
 * The vertex shader re-projects each source pixel: it remaps the depth ramp
 * onto a view distance and unprojects the plane's NDC exactly as the source
 * render camera (vertical FOV 56.35, aspect 1448/1086) did, then renders
 * through a cover-fit camera so the fixed front view matches the image.
 */
const DEPTH_VERTEX_SHADER = /* glsl */ `
  uniform sampler2D uDepth;
  uniform vec2 uParallax;
  uniform float uDolly;
  uniform float uNear;
  uniform float uFar;
  uniform float uTanHalfFov;
  uniform float uSourceAspect;
  uniform float uBleed;
  varying vec2 vUv;

  void main() {
    // uv follows the overscanned NDC, so the un-overscanned frame samples the
    // image 1:1 and the bleed margin clamps off edge pixels instead of zooming.
    vec2 ndc = position.xy * uBleed;
    vUv = ndc * 0.5 + 0.5;
    // Dark depth means near, bright means far.
    float dist = mix(uNear, uFar, texture2D(uDepth, uv).r);
    vec3 view = vec3(
      ndc.x * uTanHalfFov * uSourceAspect * dist,
      ndc.y * uTanHalfFov * dist,
      -(dist - uDolly)
    );
    // A virtual camera translation: near pixels shift more than far ones.
    view.xy -= uParallax;
    gl_Position = projectionMatrix * vec4(view, 1.0);
  }
`;

const DEPTH_FRAGMENT_SHADER = /* glsl */ `
  uniform sampler2D uColor;
  varying vec2 vUv;

  void main() {
    gl_FragColor = vec4(texture2D(uColor, vUv).rgb, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`;

function displaceSplatShell(
  geometry: THREE.SphereGeometry,
  depthTexture: THREE.Texture,
): void {
  const image = depthTexture.image as HTMLImageElement;
  const canvas = document.createElement("canvas");
  canvas.width = image.naturalWidth || image.width;
  canvas.height = image.naturalHeight || image.height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context || canvas.width === 0 || canvas.height === 0) {
    throw new Error("stage_splat_depth_unreadable");
  }
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
  const positions = geometry.getAttribute("position");
  const uvs = geometry.getAttribute("uv");
  const direction = new THREE.Vector3();
  for (let index = 0; index < positions.count; index += 1) {
    const u = THREE.MathUtils.clamp(uvs.getX(index), 0, 1);
    const v = THREE.MathUtils.clamp(uvs.getY(index), 0, 1);
    const pixelX = Math.min(canvas.width - 1, Math.floor(u * canvas.width));
    const pixelY = Math.min(
      canvas.height - 1,
      Math.floor((1 - v) * canvas.height),
    );
    const depth = pixels[(pixelY * canvas.width + pixelX) * 4] / 255;
    const radius = Math.max(depth * SPLAT_DEPTH_MAX, 0.5);
    direction
      .set(positions.getX(index), positions.getY(index), positions.getZ(index))
      .normalize()
      .multiplyScalar(radius);
    positions.setXYZ(index, direction.x, direction.y, direction.z);
  }
  positions.needsUpdate = true;
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
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

function makeSoftShadow(): THREE.DataTexture {
  const size = 64;
  const pixels = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const radius = Math.hypot(x - size / 2, y - size / 2) / (size / 2);
      const alpha = Math.max(0, 1 - radius * radius);
      const offset = (y * size + x) * 4;
      pixels[offset] = 255;
      pixels[offset + 1] = 255;
      pixels[offset + 2] = 255;
      pixels[offset + 3] = Math.round(alpha * alpha * 255);
    }
  }
  const texture = new THREE.DataTexture(pixels, size, size, THREE.RGBAFormat);
  texture.needsUpdate = true;
  return texture;
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
  private readonly shadowTexture = makeSoftShadow();
  private readonly floorBounds: THREE.Box3;
  private readonly stageCenterZ: number;
  private readonly characterHeight: number;
  private readonly onReady?: () => void;
  private readonly onError?: (error: Error) => void;
  private readonly onAnchors?: (anchors: StageAnchor[]) => void;

  private templates: THREE.Object3D[] = [];
  private templateScales: number[] = [];
  private loading = 0;
  private readonly characters: Character[] = [];
  private pending: StageCharacter[] | null = null;
  private frame: number | null = null;
  private startedAt = performance.now();
  private lastAnchorAt = 0;
  private width = 0;
  private height = 0;
  private cameraBaseZ = DEFAULT_CAMERA_Z;
  private disposed = false;
  private resting = true;
  private reducedMotion = false;

  // The splat scene has a fixed transform and shares the live stage camera.
  // There is deliberately no second camera or screen-space alignment layer.
  private splatLoaded = false;
  private splatScene: THREE.Scene | null = null;
  private sparkRenderer: SparkRenderer | null = null;
  private splatMesh: SplatMesh | null = null;
  private splatPanorama: THREE.Mesh | null = null;
  private splatPanoramaTextures: THREE.Texture[] = [];
  private splatToken = 0;
  private activeSplatPack = requestedStageScenePack();

  // Depth backdrop state stays null until ?depth=1 opts in and both textures
  // have loaded, keeping its resources out of the default and splat paths.
  private depthScene: THREE.Scene | null = null;
  private depthCamera: THREE.PerspectiveCamera | null = null;
  private depthMesh: THREE.Mesh | null = null;
  private depthMaterial: THREE.ShaderMaterial | null = null;
  private depthTextures: THREE.Texture[] = [];
  private depthLoaded = false;
  private depthToken = 0;
  private readonly activeCameraCommands = new Set<StageCameraCommand>();
  private readonly firstPersonPosition = FIRST_PERSON_START.clone();
  private cameraYaw = FIRST_PERSON_YAW;
  private cameraPitch = FIRST_PERSON_PITCH;
  private readonly cameraDirection = new THREE.Vector3();
  private readonly cameraRight = new THREE.Vector3();
  private readonly cameraLookAt = new THREE.Vector3();
  private readonly cameraCandidate = new THREE.Vector3();
  private overviewCurve: THREE.CubicBezierCurve3 | null = null;
  private readonly overviewStartQuaternion = new THREE.Quaternion();
  private readonly overviewEndQuaternion = new THREE.Quaternion();
  private overviewProgress = 0;
  private overviewTarget = 0;
  private savedFirstPerson: {
    position: THREE.Vector3;
    yaw: number;
    pitch: number;
  } | null = null;
  private renderPixelRatio = Math.min(
    window.devicePixelRatio || 1,
    MAX_RENDER_PIXEL_RATIO,
  );
  private slowFrameCount = 0;

  private readonly projection = new THREE.Vector3();
  private readonly offsetEuler = new THREE.Euler();
  private readonly offsetQuat = new THREE.Quaternion();
  private readonly armQuat = new THREE.Quaternion();
  private readonly armAxis = new THREE.Vector3();
  private readonly clock = new THREE.Clock();
  private readonly resizeHandler = () => this.resize();
  private readonly canvasClickHandler = () => {
    if (
      stageBackdropMode() === "splat" &&
      document.pointerLockElement !== this.canvas
    ) {
      void this.canvas.requestPointerLock?.();
    }
  };
  private readonly mouseMoveHandler = (event: MouseEvent) => {
    if (
      document.pointerLockElement !== this.canvas ||
      this.overviewTarget !== 0 ||
      this.overviewProgress !== 0
    ) {
      return;
    }
    this.cameraYaw -= event.movementX * STAGE_CAMERA_MOUSE_SENSITIVITY;
    this.cameraPitch = THREE.MathUtils.clamp(
      this.cameraPitch - event.movementY * STAGE_CAMERA_MOUSE_SENSITIVITY,
      -STAGE_CAMERA_PITCH_LIMIT,
      STAGE_CAMERA_PITCH_LIMIT,
    );
    this.applyStageCamera();
  };

  constructor(options: ScholarStageOptions) {
    this.canvas = options.canvas;
    this.onReady = options.onReady;
    this.onError = options.onError;
    this.onAnchors = options.onAnchors;
    const backdrop = stageBackdropMode();
    this.stageCenterZ =
      backdrop === "splat" ? SPLAT_STAGE_CENTER_Z : STAGE_CENTER_Z;
    this.characterHeight =
      backdrop === "splat" ? SPLAT_CHARACTER_HEIGHT : NORMALISED_HEIGHT;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(
      CAMERA_FOV_DEGREES,
      1,
      0.1,
      SPLAT_CAMERA_FAR,
    );
    // Figures and splat remain in world space. Navigation mutates this
    // camera only, which prevents any apparent character follow behavior.
    this.camera.position.set(0, CAMERA_HEIGHT, DEFAULT_CAMERA_Z);
    this.camera.lookAt(CAMERA_TARGET);
    this.scene.add(this.camera);

    this.scene.add(new THREE.HemisphereLight(0xffefd9, 0x687583, 1.75));
    const key = new THREE.DirectionalLight(0xffedcf, 2.15);
    key.position.set(-3.2, 4.2, 2.8);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xcbd9e9, 0.7);
    fill.position.set(3, 1.4, 2);
    this.scene.add(fill);

    this.floorBounds = this.buildFloorBounds();

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      alpha: true,
      antialias: backdrop !== "splat",
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(this.renderPixelRatio);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    if (typeof window.matchMedia === "function") {
      this.reducedMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
    }

    this.draco.setDecoderPath(STAGE_DECODER_PATH);
    this.loader.setDRACOLoader(this.draco);
    this.loader.register((parser) => {
      // Embedded GLB images belong to img-src; ImageBitmapLoader fetches them
      // through connect-src, which intentionally excludes blob: in production.
      parser.textureLoader = new THREE.TextureLoader(parser.options.manager)
        .setCrossOrigin(parser.options.crossOrigin)
        .setRequestHeader(parser.options.requestHeader);
      return { name: "MAYA_stage_image_textures" };
    });
    window.addEventListener("resize", this.resizeHandler, { passive: true });
    this.canvas.addEventListener("click", this.canvasClickHandler);
    document.addEventListener("mousemove", this.mouseMoveHandler);
    this.resize();
    this.load();
    if (backdrop === "depth") void this.loadDepthBackdrop();
    if (backdrop === "splat") void this.loadSplatBackdrop();
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
    this.applyExpression(character);
  }

  /** Attach (or clear) one participant's compiled timeline for its turns. */
  setPerformance(id: string, player: PerformancePlayer | null): void {
    const character = this.characters.find((item) => item.spec.id === id);
    if (!character) return;
    if (player === null) {
      character.performance = null;
      return;
    }
    // A fresh turn always starts its timeline at the first audio sample;
    // timeupdates resync before the render loop drifts anywhere noticeable.
    character.performance = { player, time: 0, syncTime: 0 };
  }

  /** Resync a timeline clock with the audio element's currentTime. */
  setPerformanceTime(id: string, audioTimeSec: number): void {
    const character = this.characters.find((item) => item.spec.id === id);
    if (!character?.performance) return;
    character.performance.syncTime = audioTimeSec;
  }

  moveStageCamera(command: StageCameraCommand): void {
    if (stageBackdropMode() !== "splat") return;
    // Same guard as moveFirstPerson: during the overview round trip the live
    // camera follows the transition curve, so an applyStageCamera() here would
    // teleport it back to the ground pose and freeze all camera input.
    if (this.overviewTarget !== 0 || this.overviewProgress !== 0) return;
    if (command === "turn-left" || command === "turn-right") {
      this.cameraYaw += stageCameraTurnSign(command) * STAGE_CAMERA_TURN_NUDGE;
      this.applyStageCamera();
      return;
    }
    this.moveFirstPerson(command, STAGE_CAMERA_NUDGE);
    this.applyStageCamera();
  }

  setStageCameraInput(command: StageCameraCommand, active: boolean): void {
    if (active) this.activeCameraCommands.add(command);
    else this.activeCameraCommands.delete(command);
  }

  clearStageCameraInput(): void {
    this.activeCameraCommands.clear();
  }

  setScenePack(id: string): void {
    if (stageBackdropMode() !== "splat") return;
    const next = stageScenePack(id);
    if (next.id === this.activeSplatPack.id) return;
    this.activeSplatPack = next;
    this.disposeSplatBackdrop();
    void this.loadSplatBackdrop();
  }

  resetStageCamera(): void {
    this.clearStageCameraInput();
    this.savedFirstPerson = null;
    this.overviewCurve = null;
    this.overviewProgress = 0;
    this.overviewTarget = 0;
    this.firstPersonPosition.copy(FIRST_PERSON_START);
    this.cameraYaw = FIRST_PERSON_YAW;
    this.cameraPitch = FIRST_PERSON_PITCH;
    this.applyStageCamera();
  }

  toggleStageOverview(): void {
    if (stageBackdropMode() !== "splat") return;
    if (this.overviewTarget === 1) {
      this.overviewTarget = 0;
      return;
    }
    if (this.overviewProgress > 0) {
      this.overviewTarget = 1;
      return;
    }

    this.clearStageCameraInput();
    this.savedFirstPerson = {
      position: this.firstPersonPosition.clone(),
      yaw: this.cameraYaw,
      pitch: this.cameraPitch,
    };
    const start = this.firstPersonPosition.clone();
    const rise = Math.max(1.7, (OVERVIEW_POSITION.y - start.y) * 0.55);
    this.overviewCurve = new THREE.CubicBezierCurve3(
      start,
      start.clone().add(new THREE.Vector3(0, rise, -0.7)),
      OVERVIEW_POSITION.clone().add(new THREE.Vector3(0, 0.45, 1.3)),
      OVERVIEW_POSITION,
    );
    this.overviewStartQuaternion.copy(this.camera.quaternion);
    const overviewCamera = this.camera.clone();
    overviewCamera.position.copy(OVERVIEW_POSITION);
    overviewCamera.lookAt(OVERVIEW_TARGET);
    this.overviewEndQuaternion.copy(overviewCamera.quaternion);
    this.overviewTarget = 1;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    this.frame = null;
    window.removeEventListener("resize", this.resizeHandler);
    this.canvas.removeEventListener("click", this.canvasClickHandler);
    document.removeEventListener("mousemove", this.mouseMoveHandler);
    if (document.pointerLockElement === this.canvas)
      document.exitPointerLock?.();
    for (const character of this.characters) {
      this.scene.remove(character.root);
      character.egg?.dispose();
      disposeObject(character.root, Boolean(character.egg));
      this.scene.remove(character.shadow);
      disposeObject(character.shadow);
    }
    this.characters.length = 0;
    for (const template of this.templates) {
      if (template) disposeObject(template);
    }
    this.templates.length = 0;
    this.templateScales.length = 0;
    this.shadowTexture.dispose();
    this.disposeSplatBackdrop();
    this.disposeDepthBackdrop();
    this.draco.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }

  private load(): void {
    const assets = [...STAGE_CHARACTER_ASSETS, "/avatars/Maya-Egg.glb"];
    for (const url of assets) {
      if (!isStageAssetUrl(url)) {
        this.onError?.(new Error("stage_asset_rejected"));
        return;
      }
    }
    this.loading = assets.length;
    this.templates = new Array(assets.length);
    this.templateScales = new Array(assets.length);
    assets.forEach((url, index) => {
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
            size.y > 0 ? this.characterHeight / size.y : 1;
          this.templates[index] = gltf.scene;
          this.assetLoaded();
        },
        undefined,
        (cause) => {
          this.assetFailed(cause);
        },
      );
    });
  }

  private assetLoaded(): void {
    this.loading -= 1;
    if (this.loading !== 0) return;
    if (this.pending) {
      this.rebuild(this.pending);
      this.pending = null;
    }
    this.startLoop();
    this.onReady?.();
  }

  private assetFailed(cause: unknown): void {
    if (this.disposed || this.loading < 0) return;
    this.loading = -1;
    this.onError?.(new Error("stage_asset_failed", { cause }));
  }

  /** Load the optional full-world splat with one fixed world transform. */
  private async loadSplatBackdrop(): Promise<void> {
    const token = ++this.splatToken;
    const pack = this.activeSplatPack;
    let pendingSpark: SparkRenderer | null = null;
    let pendingMesh: SplatMesh | null = null;
    try {
      const sparkModule = await import("@sparkjsdev/spark");
      if (this.disposed || token !== this.splatToken) return;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0xb7d5ec);
      const spark = new sparkModule.SparkRenderer({ renderer: this.renderer });
      pendingSpark = spark;
      scene.add(spark);
      const mesh = new sparkModule.SplatMesh({ url: pack.splatUrl });
      // BLUNT stores panorama-up as negative Y. Mirroring only that axis keeps
      // the authored longitude and metric depth aligned with the stage camera.
      mesh.scale.y = -1;
      mesh.position.copy(SPLAT_CAPTURE_ORIGIN);
      pendingMesh = mesh;
      scene.add(mesh);

      await mesh.initialized;
      if (this.disposed || token !== this.splatToken) {
        mesh.dispose();
        spark.dispose();
        return;
      }

      // A monocular lift cannot invent surfaces hidden behind depth edges.
      // The same-source far sphere fills only those holes; the visible
      // courtyard geometry and camera parallax still come from the SPZ.
      if (pack.panoramaUrl) {
        await this.loadSplatPanoramaFill(scene, token, pack.panoramaUrl);
      }
      if (this.disposed || token !== this.splatToken) {
        mesh.dispose();
        spark.dispose();
        return;
      }

      this.sparkRenderer = spark;
      this.splatMesh = mesh;
      pendingSpark = null;
      pendingMesh = null;
      this.splatScene = scene;
      this.splatLoaded = true;
      this.updateStageProjection();
      this.resetStageCamera();
      this.resize();
      return;
    } catch {
      pendingMesh?.dispose();
      pendingSpark?.dispose();
      if (this.disposed || token !== this.splatToken) return;
    }

    try {
      if (!pack.panoramaUrl || !pack.depthUrl) throw new Error("no_fallback");
      await this.loadSplatPanoramaFallback(token, pack);
    } catch {
      if (token === this.splatToken && !this.disposed) {
        // Missing Gaussian and fallback media must not fail the whole stage.
        this.disposeSplatBackdrop();
        console.warn("stage_splat_unavailable");
      }
    }
  }

  private async loadSplatPanoramaFallback(
    token: number,
    pack: StageScenePack,
  ): Promise<void> {
    let pendingPanorama: THREE.Mesh | null = null;
    let pendingPanoramaTextures: THREE.Texture[] = [];
    try {
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0xb7d5ec);
      const loader = new THREE.TextureLoader();
      const results = await Promise.allSettled([
        this.loadDepthTexture(loader, pack.panoramaUrl as string),
        this.loadDepthTexture(loader, pack.depthUrl as string),
      ]);
      pendingPanoramaTextures = results.flatMap((result) =>
        result.status === "fulfilled" ? [result.value] : [],
      );
      const failed = results.find(
        (result): result is PromiseRejectedResult =>
          result.status === "rejected",
      );
      if (failed) throw failed.reason;
      const [panoramaTexture, depthTexture] = results.map(
        (result) => (result as PromiseFulfilledResult<THREE.Texture>).value,
      );
      pendingPanoramaTextures = [panoramaTexture, depthTexture];
      if (this.disposed || token !== this.splatToken) {
        panoramaTexture.dispose();
        depthTexture.dispose();
        return;
      }
      panoramaTexture.colorSpace = THREE.SRGBColorSpace;
      depthTexture.colorSpace = THREE.NoColorSpace;
      for (const texture of [panoramaTexture, depthTexture]) {
        texture.minFilter = THREE.LinearFilter;
        texture.magFilter = THREE.LinearFilter;
        texture.wrapS = THREE.RepeatWrapping;
        texture.wrapT = THREE.ClampToEdgeWrapping;
      }
      const panoramaGeometry = new THREE.SphereGeometry(
        1,
        SPLAT_SHELL_SEGMENTS_X,
        SPLAT_SHELL_SEGMENTS_Y,
      );
      displaceSplatShell(panoramaGeometry, depthTexture);
      depthTexture.dispose();
      pendingPanoramaTextures = [panoramaTexture];
      const panorama = new THREE.Mesh(
        panoramaGeometry,
        new THREE.MeshBasicMaterial({
          map: panoramaTexture,
          side: THREE.DoubleSide,
        }),
      );
      pendingPanorama = panorama;
      // This enclosing shell is always around the navigable area. Skipping
      // per-frame culling also avoids edge flicker at deep concave sections.
      panorama.frustumCulled = false;
      panorama.rotation.y = Math.PI;
      panorama.position.copy(SPLAT_CAPTURE_ORIGIN);
      scene.add(panorama);
      if (this.disposed || token !== this.splatToken) {
        panorama.geometry.dispose();
        (panorama.material as THREE.Material).dispose();
        panoramaTexture.dispose();
        depthTexture.dispose();
        return;
      }

      this.splatPanorama = panorama;
      this.splatPanoramaTextures = [panoramaTexture];
      pendingPanorama = null;
      pendingPanoramaTextures = [];
      this.splatScene = scene;
      this.splatLoaded = true;
      this.updateStageProjection();
      this.resetStageCamera();
      this.resize();
    } catch (cause) {
      pendingPanorama?.geometry.dispose();
      if (pendingPanorama) {
        (pendingPanorama.material as THREE.Material).dispose();
      }
      pendingPanoramaTextures.forEach((texture) => texture.dispose());
      throw cause;
    }
  }

  private async loadSplatPanoramaFill(
    scene: THREE.Scene,
    token: number,
    panoramaUrl: string,
  ): Promise<void> {
    let texture: THREE.Texture | null = null;
    let panorama: THREE.Mesh | null = null;
    try {
      texture = await new THREE.TextureLoader().loadAsync(panoramaUrl);
      if (this.disposed || token !== this.splatToken) {
        texture.dispose();
        return;
      }
      texture.colorSpace = THREE.SRGBColorSpace;
      panorama = new THREE.Mesh(
        new THREE.SphereGeometry(SPLAT_PANORAMA_RADIUS, 64, 32),
        new THREE.MeshBasicMaterial({ map: texture, side: THREE.BackSide }),
      );
      panorama.rotation.y = Math.PI;
      panorama.position.copy(SPLAT_CAPTURE_ORIGIN);
      panorama.frustumCulled = false;
      scene.add(panorama);
      this.splatPanorama = panorama;
      this.splatPanoramaTextures = [texture];
    } catch {
      panorama?.geometry.dispose();
      if (panorama) (panorama.material as THREE.Material).dispose();
      texture?.dispose();
    }
  }

  private disposeSplatBackdrop(): void {
    // Any later load result sees the bump and cleans up after itself.
    this.splatToken += 1;
    const restoreProjection = this.splatLoaded && !this.disposed;
    this.splatLoaded = false;
    if (this.splatMesh) {
      this.splatMesh.dispose();
      this.splatMesh = null;
    }
    if (this.sparkRenderer) {
      this.sparkRenderer.dispose();
      this.sparkRenderer = null;
    }
    if (this.splatPanorama) {
      this.splatPanorama.geometry.dispose();
      (this.splatPanorama.material as THREE.Material).dispose();
      this.splatPanorama = null;
    }
    this.splatPanoramaTextures.forEach((texture) => texture.dispose());
    this.splatPanoramaTextures = [];
    this.splatScene = null;
    if (restoreProjection) {
      this.updateStageProjection();
      this.updateCameraFraming();
    }
  }

  /**
   * The depth backdrop loads as one all-or-nothing unit: any failed texture
   * leaves the CSS courtyard untouched.
   */
  private async loadDepthBackdrop(): Promise<void> {
    const token = ++this.depthToken;
    const loader = new THREE.TextureLoader();
    let colorTexture: THREE.Texture | null = null;
    let depthTexture: THREE.Texture | null = null;
    let geometry: THREE.PlaneGeometry | null = null;
    let material: THREE.ShaderMaterial | null = null;
    let adopted = false;
    try {
      // allSettled so a fulfilled texture never leaks when the other fails.
      const results = await Promise.allSettled([
        this.loadDepthTexture(loader, STAGE_DEPTH_COLOR_URL),
        this.loadDepthTexture(loader, STAGE_DEPTH_MAP_URL),
      ]);
      const failed = results.find(
        (result): result is PromiseRejectedResult =>
          result.status === "rejected",
      );
      if (failed) throw failed.reason;
      [colorTexture, depthTexture] = results.map(
        (result) => (result as PromiseFulfilledResult<THREE.Texture>).value,
      );
      if (this.disposed || token !== this.depthToken) return;

      geometry = new THREE.PlaneGeometry(
        2,
        2,
        DEPTH_MESH_SEGMENTS_X,
        DEPTH_MESH_SEGMENTS_Y,
      );
      material = new THREE.ShaderMaterial({
        vertexShader: DEPTH_VERTEX_SHADER,
        fragmentShader: DEPTH_FRAGMENT_SHADER,
        uniforms: {
          uColor: { value: colorTexture },
          uDepth: { value: depthTexture },
          uParallax: { value: new THREE.Vector2(0, 0) },
          uDolly: { value: 0 },
          uNear: { value: DEPTH_NEAR },
          uFar: { value: DEPTH_FAR },
          // The source camera constants: NDC is unprojected exactly as the
          // courtyard was rendered, so the fixed view keeps the composition.
          uTanHalfFov: {
            value: Math.tan(
              THREE.MathUtils.degToRad(DEPTH_CAMERA_FOV_DEGREES / 2),
            ),
          },
          uSourceAspect: { value: DEPTH_SOURCE_ASPECT },
          uBleed: { value: DEPTH_EDGE_BLEED },
        },
      });
      colorTexture.colorSpace = THREE.SRGBColorSpace;
      depthTexture.colorSpace = THREE.NoColorSpace;
      for (const texture of [colorTexture, depthTexture]) {
        // Mipmaps would average neighbouring depths and bleed displacement
        // across silhouette edges, so the source resolution is kept.
        texture.minFilter = THREE.LinearFilter;
        texture.magFilter = THREE.LinearFilter;
        texture.wrapS = THREE.ClampToEdgeWrapping;
        texture.wrapT = THREE.ClampToEdgeWrapping;
      }

      const mesh = new THREE.Mesh(geometry, material);
      mesh.frustumCulled = false;
      const scene = new THREE.Scene();
      scene.add(mesh);
      const camera = new THREE.PerspectiveCamera(
        depthCameraFov(this.camera.aspect),
        this.camera.aspect,
        0.1,
        DEPTH_CAMERA_FAR,
      );
      // The unprojection happens in the shader, so the render camera just
      // frames the result from the source viewpoint (origin, looking -Z).
      camera.position.set(0, 0, 0);
      camera.lookAt(0, 0, -1);

      this.depthTextures = [colorTexture, depthTexture];
      this.depthMaterial = material;
      this.depthMesh = mesh;
      this.depthScene = scene;
      this.depthCamera = camera;
      adopted = true;
      this.depthLoaded = true;
      this.resize();
    } catch (cause) {
      if (token === this.depthToken && !this.disposed) {
        // The stage's onError flips the whole scene to "failed", so a missing
        // depth asset only logs and keeps the CSS backdrop fallback.
        console.warn("stage_depth_unavailable", cause);
      }
    } finally {
      if (!adopted) {
        colorTexture?.dispose();
        depthTexture?.dispose();
        material?.dispose();
        geometry?.dispose();
      }
    }
  }

  private loadDepthTexture(
    loader: THREE.TextureLoader,
    url: string,
  ): Promise<THREE.Texture> {
    return new Promise<THREE.Texture>((resolve, reject) => {
      loader.load(url, resolve, undefined, (cause) => {
        reject(
          cause instanceof Error
            ? cause
            : new Error("stage_depth_texture_failed"),
        );
      });
    });
  }

  private disposeDepthBackdrop(): void {
    // Any later load result sees the bump and cleans up after itself.
    this.depthToken += 1;
    this.depthLoaded = false;
    if (this.depthMesh) {
      this.depthScene?.remove(this.depthMesh);
      this.depthMesh.geometry.dispose();
      this.depthMesh = null;
    }
    if (this.depthMaterial) {
      this.depthMaterial.dispose();
      this.depthMaterial = null;
    }
    for (const texture of this.depthTextures) texture.dispose();
    this.depthTextures = [];
    this.depthScene = null;
    this.depthCamera = null;
  }

  /**
   * A non-renderable box gives every figure the same collision surface. It is
   * data rather than scene geometry, so no material can leak into the image.
   */
  private buildFloorBounds(): THREE.Box3 {
    return new THREE.Box3(
      new THREE.Vector3(
        -FLOOR_COLLIDER_WIDTH / 2,
        FLOOR_Y - FLOOR_COLLIDER_THICKNESS,
        this.stageCenterZ - FLOOR_COLLIDER_DEPTH / 2,
      ),
      new THREE.Vector3(
        FLOOR_COLLIDER_WIDTH / 2,
        FLOOR_Y,
        this.stageCenterZ + FLOOR_COLLIDER_DEPTH / 2,
      ),
    );
  }

  /** Resolve vertical overlap against the slab and return its top surface. */
  private groundCharacter(root: THREE.Object3D): number {
    root.updateWorldMatrix(true, true);
    const body = new THREE.Box3();
    root.traverse((object) => {
      if (!isMorphMesh(object) || !object.visible) return;
      let ancestor = object.parent;
      while (ancestor && ancestor !== root) {
        if (!ancestor.visible) return;
        ancestor = ancestor.parent;
      }
      if (!object.geometry.boundingBox) object.geometry.computeBoundingBox();
      if (object.geometry.boundingBox) {
        body.union(
          object.geometry.boundingBox.clone().applyMatrix4(object.matrixWorld),
        );
      }
    });
    const floor = this.floorBounds;
    if (body.isEmpty()) return floor.max.y;
    const center = body.getCenter(new THREE.Vector3());
    const insideFloor =
      center.x >= floor.min.x &&
      center.x <= floor.max.x &&
      center.z >= floor.min.z &&
      center.z <= floor.max.z;
    const groundY = insideFloor ? floor.max.y : FLOOR_Y;
    root.position.y += groundY - body.min.y;
    return groundY;
  }

  private rebuild(specs: StageCharacter[]): void {
    for (const character of this.characters) {
      this.scene.remove(character.root);
      character.egg?.dispose();
      disposeObject(character.root, Boolean(character.egg));
      this.scene.remove(character.shadow);
      disposeObject(character.shadow);
    }
    this.characters.length = 0;
    if (this.templates.length === 0) return;

    specs.forEach((spec, index) => {
      // Deterministic variant per seat: load order is the roster order, so a
      // given roster always renders the same mix of the two figures.
      const isEgg = spec.config.template_id === "egg";
      const templateIndex = isEgg
        ? STAGE_CHARACTER_ASSETS.length
        : index % STAGE_CHARACTER_ASSETS.length;
      const root = cloneSkinned(
        this.templates[templateIndex] as THREE.Object3D,
      );
      const egg = isEgg ? prepareEggModel(root, spec.config.drawing) : null;
      root.scale.setScalar(
        isEgg ? this.characterHeight / 2.7 : this.templateScales[templateIndex],
      );
      const offset = standingPlacement(spec.slot);
      const standingX = offset.x;
      const standingZ = this.stageCenterZ + offset.z;
      root.position.set(standingX, 0, standingZ);
      root.rotation.y = offset.yaw;
      // Root-local hang directions keep the same rest pose after the seat yaw.
      applyRelaxedStandingPose(
        root,
        hangProfileForAsset(STAGE_CHARACTER_ASSETS[templateIndex] ?? ""),
      );
      const meshes: MorphMesh[] = [];
      if (!isEgg) this.styleFigure(root, spec.config, meshes);
      const groundY = this.groundCharacter(root);
      const shadow = new THREE.Mesh(
        new THREE.CircleGeometry(0.34, 32),
        new THREE.MeshBasicMaterial({
          color: 0x34291e,
          map: this.shadowTexture,
          transparent: true,
          opacity: 0.4,
          depthWrite: false,
        }),
      );
      shadow.rotation.x = -Math.PI / 2;
      shadow.scale.y = 0.58;
      shadow.position.set(standingX, groundY + 0.004, standingZ);
      this.scene.add(shadow);

      const headBone = findBone(root, "head");
      const neckBone = findBone(root, "neck");
      const torsoBone = findBone(root, "torso");
      const jawBone = findBone(root, "jaw");
      const upperArmLBone = findBone(root, "upperArmL");
      const upperArmRBone = findBone(root, "upperArmR");
      const forearmLBone = findBone(root, "forearmL");
      const forearmRBone = findBone(root, "forearmR");
      const handLBone = findBone(root, "handL");
      const handRBone = findBone(root, "handR");

      // Figure-frame (root-yaw removed) parent orientation per arm bone; the
      // player's figure-space steps convert to bone-local against these.
      const rootRestQ = root.getWorldQuaternion(new THREE.Quaternion());
      const figureParent = (
        bone: THREE.Object3D | null,
        rest: THREE.Quaternion | null,
      ): THREE.Quaternion | null => {
        if (!bone || !rest) return null;
        const world = bone.getWorldQuaternion(new THREE.Quaternion());
        return rootRestQ
          .clone()
          .invert()
          .multiply(world)
          .multiply(rest.clone().invert());
      };
      const upperArmLRest = upperArmLBone?.quaternion.clone() ?? null;
      const upperArmRRest = upperArmRBone?.quaternion.clone() ?? null;
      const foreArmLRest = forearmLBone?.quaternion.clone() ?? null;
      const foreArmRRest = forearmRBone?.quaternion.clone() ?? null;
      const handLRestQ = handLBone?.quaternion.clone() ?? null;
      const handRRestQ = handRBone?.quaternion.clone() ?? null;

      const character: Character = {
        egg,
        spec,
        root,
        shadow,
        meshes,
        headBone,
        headRest: headBone?.quaternion.clone() ?? null,
        neckBone,
        neckRest: neckBone?.quaternion.clone() ?? null,
        torsoBone,
        torsoRest: torsoBone?.quaternion.clone() ?? null,
        upperArmLBone,
        upperArmLRest,
        upperArmLParentRest: figureParent(upperArmLBone, upperArmLRest),
        upperArmRBone,
        upperArmRRest,
        upperArmRParentRest: figureParent(upperArmRBone, upperArmRRest),
        forearmLBone,
        forearmLRest: foreArmLRest,
        forearmLParentRest: figureParent(forearmLBone, foreArmLRest),
        forearmRBone,
        forearmRRest: foreArmRRest,
        forearmRParentRest: figureParent(forearmRBone, foreArmRRest),
        handLBone,
        handLRest: handLRestQ,
        handLParentRest: figureParent(handLBone, handLRestQ),
        handRBone,
        handRRest: handRRestQ,
        handRParentRest: figureParent(handRBone, handRRestQ),
        jawBone,
        jawRest: jawBone?.quaternion.clone() ?? null,
        hasSpeechMorph: meshes.some(
          (mesh) =>
            mesh.morphTargetDictionary?.mouthOpen !== undefined ||
            mesh.morphTargetDictionary?.jawOpen !== undefined,
        ),
        seatYaw: offset.yaw,
        state: "idle",
        stateStartedAt: performance.now(),
        performance: null,
      };
      this.applyExpression(character);
      this.scene.add(root);
      this.characters.push(character);
    });
    this.updateCameraFraming();
  }

  /**
   * Keep every reserved slot and bubbles inside the reset view.
   */
  private updateCameraFraming(): void {
    if (stageBackdropMode() === "splat") {
      this.applyStageCamera();
      return;
    }
    // Imported skinned-mesh bounds include distant rig helpers; frame the
    // authored standing ring instead of letting those helpers shrink the stage.
    const outer = STAGE_STANDING_RADIUS + 0.5;
    const halfWidth = outer * CAMERA_EDGE_MARGIN;
    const aspect = Math.max(this.camera.aspect, 0.1);
    const halfFovRadians = THREE.MathUtils.degToRad(this.camera.fov / 2);
    const requiredDistance =
      halfWidth / Math.tan(halfFovRadians) / aspect +
      STAGE_STANDING_RADIUS +
      CAMERA_DEPTH_MARGIN;
    const rosterSize = this.pending?.length ?? this.characters.length;
    const distance =
      aspect < 0.75 && rosterSize === 2
        ? requiredDistance * 0.86
        : requiredDistance;
    this.cameraBaseZ = Math.max(DEFAULT_CAMERA_Z, distance);
    this.applyStageCamera();
  }

  private applyStageCamera(): void {
    if (stageBackdropMode() !== "splat") {
      this.camera.position.set(0, CAMERA_HEIGHT, this.cameraBaseZ);
      this.camera.lookAt(CAMERA_TARGET);
      return;
    }

    this.camera.position.copy(this.firstPersonPosition);
    const horizontal = Math.cos(this.cameraPitch);
    this.cameraDirection.set(
      Math.sin(this.cameraYaw) * horizontal,
      Math.sin(this.cameraPitch),
      Math.cos(this.cameraYaw) * horizontal,
    );
    this.cameraLookAt
      .copy(this.camera.position)
      .addScaledVector(this.cameraDirection, 10);
    this.camera.lookAt(this.cameraLookAt);
  }

  private moveFirstPerson(command: StageCameraCommand, distance: number): void {
    if (this.overviewTarget !== 0 || this.overviewProgress !== 0) return;
    const forward = command === "forward" || command === "backward";
    const direction = command === "backward" || command === "left" ? -1 : 1;
    if (!forward && command !== "left" && command !== "right") return;

    this.cameraDirection.set(
      Math.sin(this.cameraYaw),
      0,
      Math.cos(this.cameraYaw),
    );
    this.cameraRight.set(
      -Math.cos(this.cameraYaw),
      0,
      Math.sin(this.cameraYaw),
    );
    const axis = forward ? this.cameraDirection : this.cameraRight;
    this.moveCameraWithCollision(
      axis.x * distance * direction,
      axis.z * distance * direction,
    );
  }

  private moveCameraWithCollision(dx: number, dz: number): void {
    this.cameraCandidate.copy(this.firstPersonPosition);
    this.cameraCandidate.x += dx;
    if (!this.cameraPositionBlocked(this.cameraCandidate)) {
      this.firstPersonPosition.x = this.cameraCandidate.x;
    }
    this.cameraCandidate.copy(this.firstPersonPosition);
    this.cameraCandidate.z += dz;
    if (!this.cameraPositionBlocked(this.cameraCandidate)) {
      this.firstPersonPosition.z = this.cameraCandidate.z;
    }
  }

  private cameraPositionBlocked(position: THREE.Vector3): boolean {
    return stageCameraPositionBlocked(
      position,
      SPLAT_CAPTURE_ORIGIN,
      this.stageCenterZ,
    );
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
      // The elder FBX carries a wide decorative plane named "aa" and a
      // sibling watermark text mesh from the marketplace shop; both would
      // otherwise float visibly across the classroom stage.
      if (object.name === "aa" || object.name.includes("淘宝")) {
        object.visible = false;
        return;
      }
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
    character.egg?.frame(
      elapsed,
      character.state === "speaking",
      this.reducedMotion,
    );
    const yawTarget = stageBodyYawTarget(
      character.seatYaw,
      character.state === "speaking",
    );
    if (this.reducedMotion) {
      character.root.rotation.y = yawTarget;
    } else {
      const current = character.root.rotation.y;
      const step = shortestYawDelta(current, yawTarget);
      character.root.rotation.y =
        current + step * (1 - Math.exp(-SPEAK_YAW_LAMBDA * delta));
    }
    if (character.egg) {
      character.root.updateMatrixWorld(true);
      return;
    }
    const stateElapsed = (performance.now() - character.stateStartedAt) / 1000;
    const frame = avatarMotionFrame(
      this.reducedMotion ? "idle" : character.state,
      elapsed,
      stateElapsed,
      character.spec.config.motion_style,
    );

    // Timelines are enhancement-only: while one is attached and its owner
    // speaks, it drives the mouth and layers small gesture offsets on the
    // procedural frame; every other case falls through to the old path.
    let sample: PerformanceSample | null = null;
    const timeline = character.performance;
    if (timeline && character.state === "speaking" && !this.reducedMotion) {
      if (timeline.syncTime !== null) {
        timeline.time = THREE.MathUtils.clamp(
          timeline.syncTime,
          0,
          timeline.player.duration,
        );
        timeline.syncTime = null;
      } else {
        timeline.time = Math.min(
          timeline.time + delta,
          timeline.player.duration,
        );
      }
      sample = timeline.player.sample(timeline.time);
    }

    const calm = this.reducedMotion ? 0 : this.resting ? 0.45 : 1;
    const layer = (
      offset: BoneOffset | null,
      x: number,
      y: number,
      z: number,
    ): [number, number, number] => [
      x + (offset?.[0] ?? 0),
      y + (offset?.[1] ?? 0),
      z + (offset?.[2] ?? 0),
    ];
    this.setRotation(
      character.torsoBone,
      character.torsoRest,
      ...layer(
        sample?.torso ?? null,
        frame.rotationX * 0.35 * calm,
        frame.rotationY * 0.5 * calm,
        frame.rotationZ * calm,
      ),
    );
    this.setRotation(
      character.neckBone,
      character.neckRest,
      ...layer(
        sample?.neck ?? null,
        frame.rotationX * 0.5 * calm,
        frame.rotationY * 0.6 * calm,
        0,
      ),
    );
    this.setRotation(
      character.headBone,
      character.headRest,
      ...layer(
        sample?.head ?? null,
        frame.rotationX * calm,
        frame.rotationY * calm,
        frame.rotationZ * 0.6 * calm,
      ),
    );
    // Timeline arm channels are figure-space step lists converted per rig
    // against the captures taken at load; the procedural frame never moves
    // the arms, so there is nothing to blend against here. Figures without
    // arm bones skip every channel.
    this.setArmRotation(
      character.upperArmLBone,
      character.upperArmLRest,
      character.upperArmLParentRest,
      sample?.upperArmL ?? null,
    );
    this.setArmRotation(
      character.upperArmRBone,
      character.upperArmRRest,
      character.upperArmRParentRest,
      sample?.upperArmR ?? null,
    );
    this.setArmRotation(
      character.forearmLBone,
      character.forearmLRest,
      character.forearmLParentRest,
      sample?.forearmL ?? null,
    );
    this.setArmRotation(
      character.forearmRBone,
      character.forearmRRest,
      character.forearmRParentRest,
      sample?.forearmR ?? null,
    );
    this.setArmRotation(
      character.handLBone,
      character.handLRest,
      character.handLParentRest,
      sample?.handL ?? null,
    );
    this.setArmRotation(
      character.handRBone,
      character.handRRest,
      character.handRParentRest,
      sample?.handR ?? null,
    );

    // A timed viseme window wins over the procedural mouth while speaking;
    // a timeline without visemes (mouth null) keeps the procedural one.
    const timedMouth = sample && sample.mouth !== null ? sample.mouth : null;
    for (const mesh of character.meshes) {
      const dictionary = mesh.morphTargetDictionary;
      const influences = mesh.morphTargetInfluences;
      if (!dictionary || !influences) continue;
      const mouth = dictionary.mouthOpen;
      const jaw = dictionary.jawOpen;
      if (character.state === "speaking") {
        if (timedMouth !== null) {
          if (mouth !== undefined) influences[mouth] = timedMouth;
          if (jaw !== undefined) influences[jaw] = timedMouth;
        } else {
          if (mouth !== undefined) influences[mouth] = frame.mouthOpen;
          if (jaw !== undefined) influences[jaw] = frame.jawOpen;
        }
      } else {
        if (mouth !== undefined) influences[mouth] *= 0.8;
        if (jaw !== undefined) influences[jaw] *= 0.8;
      }
    }

    // Figures without morph targets still speak: rotate the jaw bone by the
    // same motion frame and settle back to its rest pose when not talking.
    if (character.jawBone && character.jawRest) {
      if (character.state === "speaking" && !character.hasSpeechMorph) {
        this.setRotation(
          character.jawBone,
          character.jawRest,
          (timedMouth ?? frame.jawOpen) * JAW_OPEN_ANGLE,
          0,
          0,
        );
      } else {
        character.jawBone.quaternion.copy(character.jawRest);
      }
    }
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

  /**
   * Apply figure-space rotation steps (see ArmStep) to an arm bone. The steps
   * compose about figure-fixed axes; converting them through the parent's
   * rest orientation yields the bone-local quaternion, so clips read the same
   * on rigs whose bone-local axes are oriented differently. Steps compose in
   * list order — the first step rotates the rested limb, each later step
   * rotates the result further.
   */
  private setArmRotation(
    bone: THREE.Object3D | null,
    rest: THREE.Quaternion | null,
    parentRest: THREE.Quaternion | null,
    steps: readonly ArmStep[] | null,
  ): void {
    if (!bone || !rest || !parentRest) return;
    if (!steps || steps.length === 0) {
      bone.quaternion.copy(rest);
      return;
    }
    this.armQuat.identity();
    for (const [x, y, z, angle] of steps) {
      this.armAxis.set(x, y, z);
      if (!angle || this.armAxis.lengthSq() < 1e-8) continue;
      this.armAxis.normalize();
      this.offsetQuat.setFromAxisAngle(this.armAxis, angle);
      this.armQuat.premultiply(this.offsetQuat);
    }
    // Figure-frame premultiplier E becomes the local offset A⁻¹·E·A, applied
    // on top of the captured rest orientation.
    bone.quaternion
      .copy(parentRest)
      .invert()
      .multiply(this.armQuat)
      .multiply(parentRest)
      .multiply(rest);
  }

  private emitAnchors(now: number): void {
    if (!this.onAnchors || now - this.lastAnchorAt < ANCHOR_INTERVAL_MS) return;
    this.lastAnchorAt = now;
    const anchors: StageAnchor[] = [];
    for (const character of this.characters) {
      if (character.egg) {
        eggCrownWorldPosition(character.root, this.projection);
      } else {
        const bone = character.headBone ?? character.root;
        bone.getWorldPosition(this.projection);
        this.projection.y += 0.18;
      }
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
      if (stageBackdropMode() === "splat") {
        this.updateStageCamera(delta);
        this.adaptRendererResolution(delta);
      }
      if (this.depthLoaded && this.depthScene && this.depthCamera) {
        this.updateDepthMotion(elapsed);
        this.renderer.autoClear = false;
        this.renderer.clear();
        this.renderer.render(this.depthScene, this.depthCamera);
        // The depth backdrop pass writes real depth; clear it before the
        // figures or the backdrop's z-buffer values would cull them.
        this.renderer.clearDepth();
      } else if (this.splatLoaded && this.splatScene) {
        this.renderer.autoClear = false;
        this.renderer.clear();
        this.renderer.render(this.splatScene, this.camera);
        // The splat pass never writes depth, so clear it before the opaque
        // figures or the depth buffer from the backdrop would cull them.
        this.renderer.clearDepth();
      }
      for (const character of this.characters) {
        this.animateCharacter(character, delta, elapsed);
      }
      this.renderer.render(this.scene, this.camera);
      this.renderer.autoClear = true;
      this.emitAnchors(performance.now());
      this.frame = requestAnimationFrame(step);
    };
    this.frame = requestAnimationFrame(step);
  }

  private updateStageCamera(delta: number): void {
    if (this.overviewCurve && this.overviewProgress !== this.overviewTarget) {
      const direction = this.overviewTarget > this.overviewProgress ? 1 : -1;
      this.overviewProgress = THREE.MathUtils.clamp(
        this.overviewProgress +
          direction * (delta / OVERVIEW_TRANSITION_SECONDS),
        0,
        1,
      );
      const eased = THREE.MathUtils.smootherstep(this.overviewProgress, 0, 1);
      this.overviewCurve.getPoint(eased, this.camera.position);
      this.camera.quaternion
        .copy(this.overviewStartQuaternion)
        .slerp(this.overviewEndQuaternion, eased);
      if (this.overviewProgress === 0 && this.savedFirstPerson) {
        this.firstPersonPosition.copy(this.savedFirstPerson.position);
        this.cameraYaw = this.savedFirstPerson.yaw;
        this.cameraPitch = this.savedFirstPerson.pitch;
        this.savedFirstPerson = null;
        this.overviewCurve = null;
        this.applyStageCamera();
      }
      return;
    }
    if (this.overviewProgress === 1) return;

    const turn =
      (this.activeCameraCommands.has("turn-left") ? 1 : 0) -
      (this.activeCameraCommands.has("turn-right") ? 1 : 0);
    if (turn) this.cameraYaw += turn * STAGE_CAMERA_TURN_SPEED * delta;

    const forward =
      (this.activeCameraCommands.has("forward") ? 1 : 0) -
      (this.activeCameraCommands.has("backward") ? 1 : 0);
    const lateral =
      (this.activeCameraCommands.has("right") ? 1 : 0) -
      (this.activeCameraCommands.has("left") ? 1 : 0);
    if (forward || lateral) {
      this.cameraDirection.set(
        Math.sin(this.cameraYaw),
        0,
        Math.cos(this.cameraYaw),
      );
      this.cameraRight.set(
        -Math.cos(this.cameraYaw),
        0,
        Math.sin(this.cameraYaw),
      );
      const length = Math.hypot(forward, lateral) || 1;
      const distance = (STAGE_CAMERA_MOVE_SPEED * delta) / length;
      this.moveCameraWithCollision(
        (this.cameraDirection.x * forward + this.cameraRight.x * lateral) *
          distance,
        (this.cameraDirection.z * forward + this.cameraRight.z * lateral) *
          distance,
      );
    }
    this.applyStageCamera();
  }

  private adaptRendererResolution(delta: number): void {
    if (delta > SLOW_FRAME_SECONDS) this.slowFrameCount += 1;
    else this.slowFrameCount = Math.max(0, this.slowFrameCount - 2);
    if (
      this.slowFrameCount < SLOW_FRAME_THRESHOLD ||
      this.renderPixelRatio <= MIN_RENDER_PIXEL_RATIO
    ) {
      return;
    }
    this.slowFrameCount = 0;
    this.renderPixelRatio = Math.max(
      MIN_RENDER_PIXEL_RATIO,
      this.renderPixelRatio - 0.25,
    );
    this.renderer.setPixelRatio(this.renderPixelRatio);
    this.renderer.setSize(this.width, this.height, false);
  }

  /**
   * A near-imperceptible virtual camera sway, disabled for reduced motion.
   * The mesh's overscan border absorbs the shift so no gap ever shows.
   */
  private updateDepthMotion(elapsed: number): void {
    if (!this.depthMaterial) return;
    const drift = this.reducedMotion
      ? 0
      : DEPTH_PARALLAX_SCALE * (DEPTH_FAR - DEPTH_NEAR);
    this.depthMaterial.uniforms.uParallax.value.set(
      Math.sin(elapsed * 0.11) * drift,
      Math.cos(elapsed * 0.14) * drift,
    );
    this.depthMaterial.uniforms.uDolly.value = 0;
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
    this.updateStageProjection();
    this.updateCameraFraming();
    if (this.depthCamera) {
      const aspect = this.camera.aspect;
      this.depthCamera.aspect = aspect;
      this.depthCamera.fov = depthCameraFov(aspect);
      this.depthCamera.updateProjectionMatrix();
    }
    this.renderer.setSize(width, height, false);
  }

  private updateStageProjection(): void {
    this.camera.fov = this.splatLoaded
      ? stageSplatCameraFov(this.camera.aspect)
      : CAMERA_FOV_DEGREES;
    this.camera.updateProjectionMatrix();
  }
}
