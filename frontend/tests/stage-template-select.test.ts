import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AVATAR_FITTED_HANG,
  AVATAR_ROBE_HANG,
  avatarAssetUrlForTemplate,
  hangProfileForAsset,
  type AvatarConfig,
} from "../components/avatar";
import { STAGE_CHARACTER_ASSETS } from "../components/stage3d/assets";
import {
  ScholarStage,
  type StageCharacter,
  type StageSlot,
} from "../components/stage3d/scholar-stage";

const renderer = vi.hoisted(() => ({ render: vi.fn() }));

vi.mock("three", async (importOriginal) => {
  const three = await importOriginal<typeof import("three")>();
  return {
    ...three,
    WebGLRenderer: class {
      render = renderer.render;
      setPixelRatio() {}
      setSize() {}
      dispose() {}
      forceContextLoss() {}
    },
  };
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  renderer.render.mockClear();
});

const BASE_CONFIG: AvatarConfig = {
  template_id: "wave1-default-head",
  material_theme: "demo",
  eye_color: null,
  default_expression: "neutral",
  expression_strength: "medium",
  motion_style: "calm",
};

function character(
  id: string,
  templateId: string,
  slot: StageSlot = "A",
): StageCharacter {
  return {
    id,
    slot,
    name: id,
    config: { ...BASE_CONFIG, template_id: templateId },
  };
}

function mountStage() {
  const loaded: string[] = [];
  let nextFrame: FrameRequestCallback = () => {};
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    nextFrame = callback;
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  vi.spyOn(GLTFLoader.prototype, "load").mockImplementation((url, onLoad) => {
    loaded.push(url);
    const scene = new THREE.Group();
    scene.name = url;
    if (url.endsWith("Maya-Egg.glb")) {
      for (const name of ["Shell", "Mouth", "Hand_L", "Hand_R", "Foot_L", "Foot_R"]) {
        const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.2, 0.2));
        mesh.name = name;
        scene.add(mesh);
      }
    }
    onLoad({ scene } as Parameters<NonNullable<typeof onLoad>>[0]);
  });
  const stage = new ScholarStage({
    canvas: document.createElement("canvas"),
  });
  return {
    stage,
    loaded,
    frame: () => nextFrame(0),
  };
}

function meshNames(): string[] {
  const scene = renderer.render.mock.calls.at(-1)![0] as THREE.Scene;
  return scene.children
    .filter((child) => typeof child.name === "string" && child.name.startsWith("/avatars/"))
    .map((child) => child.name);
}

describe("stage template selection", () => {
  it("preloads the four registered catalog meshes and nothing else", () => {
    const { stage, loaded } = mountStage();
    try {
      expect([...loaded].sort()).toEqual([...STAGE_CHARACTER_ASSETS].sort());
      expect(loaded).toHaveLength(4);
      expect(loaded).toEqual(
        expect.arrayContaining([
          "/avatars/female_1.glb",
          "/avatars/elder-scholar.glb",
          "/avatars/noble-scholar.glb",
          "/avatars/Maya-Egg.glb",
        ]),
      );
    } finally {
      stage.dispose();
    }
  });

  it("maps each catalog template_id the same way the settings preview does", () => {
    expect(avatarAssetUrlForTemplate("wave1-default-head")).toBe(
      "/avatars/female_1.glb",
    );
    expect(avatarAssetUrlForTemplate("maya-warm-scholar")).toBe(
      "/avatars/elder-scholar.glb",
    );
    expect(avatarAssetUrlForTemplate("maya-civic-observer")).toBe(
      "/avatars/noble-scholar.glb",
    );
    expect(avatarAssetUrlForTemplate("egg")).toBe("/avatars/Maya-Egg.glb");
    expect(avatarAssetUrlForTemplate("not-a-template")).toBe(
      "/avatars/female_1.glb",
    );
  });

  it("gives default female templates female_1 on every seat, never a scholar rotation", () => {
    const { stage, frame } = mountStage();
    const specs = (["A", "B", "C", "D", "E"] as const).map((slot, index) =>
      character(`speaker-${index}`, "wave1-default-head", slot),
    );
    try {
      stage.setCharacters(specs);
      frame();
      const names = meshNames();
      expect(names).toHaveLength(5);
      expect(names.every((name) => name === "/avatars/female_1.glb")).toBe(true);
      expect(names).not.toContain("/avatars/elder-scholar.glb");
      expect(names).not.toContain("/avatars/noble-scholar.glb");
    } finally {
      stage.dispose();
    }
  });

  it("clones each mixed-roster speaker from its own template and shares one preload", () => {
    const { stage, loaded, frame } = mountStage();
    const specs = [
      character("mozi", "wave1-default-head", "A"),
      character("warm", "maya-warm-scholar", "B"),
      character("civic", "maya-civic-observer", "C"),
      character("egg", "egg", "D"),
      character("mozi-2", "wave1-default-head", "E"),
    ];
    try {
      stage.setCharacters(specs);
      frame();
      expect(loaded).toHaveLength(4);
      const names = meshNames();
      expect(names.filter((name) => name === "/avatars/female_1.glb")).toHaveLength(2);
      expect(names.filter((name) => name === "/avatars/elder-scholar.glb")).toHaveLength(1);
      expect(names.filter((name) => name === "/avatars/noble-scholar.glb")).toHaveLength(1);
      expect(names.filter((name) => name === "/avatars/Maya-Egg.glb")).toHaveLength(1);
    } finally {
      stage.dispose();
    }
  });

  it("falls unknown or illegal template_id back to female_1, not a scholar", () => {
    const { stage, frame } = mountStage();
    const specs = [
      character("unknown", "definitely-not-registered", "A"),
      character("empty", "", "B"),
    ];
    try {
      stage.setCharacters(specs);
      frame();
      const names = meshNames();
      expect(names).toEqual([
        "/avatars/female_1.glb",
        "/avatars/female_1.glb",
      ]);
    } finally {
      stage.dispose();
    }
  });

  it("rebuilds a speaker onto the new mesh after a published template change", () => {
    const { stage, loaded, frame } = mountStage();
    try {
      stage.setCharacters([character("mozi", "maya-warm-scholar", "A")]);
      frame();
      expect(meshNames()).toEqual(["/avatars/elder-scholar.glb"]);
      stage.setCharacters([character("mozi", "wave1-default-head", "A")]);
      frame();
      expect(meshNames()).toEqual(["/avatars/female_1.glb"]);
      expect(loaded).toHaveLength(4);
    } finally {
      stage.dispose();
    }
  });

  it("keeps fitted hang on the female mesh and robe hang on both scholars", () => {
    expect(hangProfileForAsset("/avatars/female_1.glb")).toBe(AVATAR_FITTED_HANG);
    expect(hangProfileForAsset("/avatars/elder-scholar.glb")).toBe(
      AVATAR_ROBE_HANG,
    );
    expect(hangProfileForAsset("/avatars/noble-scholar.glb")).toBe(
      AVATAR_ROBE_HANG,
    );
  });
});
