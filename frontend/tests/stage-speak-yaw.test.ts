import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { afterEach, describe, expect, it, vi } from "vitest";

import { stageMouthVisual } from "../components/debate-beta/stage/mouth-sync";
import { STAGE_CHARACTER_ASSETS } from "../components/stage3d/assets";
import { standingPlacement } from "../components/stage3d/placement";
import {
  ScholarStage,
  type StageCharacter,
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

describe("stage speaking body yaw", () => {
  it.each(STAGE_CHARACTER_ASSETS)(
    "%s faces front on live audio and restores its seat yaw afterwards",
    (asset) => {
      let nextFrame: FrameRequestCallback;
      vi.stubGlobal(
        "requestAnimationFrame",
        (callback: FrameRequestCallback) => {
          nextFrame = callback;
          return 1;
        },
      );
      vi.stubGlobal("cancelAnimationFrame", vi.fn());
      vi.spyOn(THREE.Clock.prototype, "getDelta").mockReturnValue(0.1);
      vi.spyOn(GLTFLoader.prototype, "load").mockImplementation(
        (url, onLoad) => {
          const scene = new THREE.Group();
          scene.name = url;
          onLoad({ scene } as Parameters<NonNullable<typeof onLoad>>[0]);
        },
      );

      const stage = new ScholarStage({
        canvas: document.createElement("canvas"),
      });
      const characters: StageCharacter[] = STAGE_CHARACTER_ASSETS.map(
        (url, index) => ({
          id: url,
          slot: (["A", "B", "C"] as const)[index],
          name: url,
          config: {
            template_id: "wave1-default-head",
            material_theme: "demo",
            eye_color: null,
            default_expression: "neutral",
            expression_strength: "medium",
            motion_style: "calm",
          },
        }),
      );
      const frame = () => nextFrame(0);
      const visual = (audioPlayingTurnId: string | null) => {
        for (const character of characters) {
          stage.setVisual(
            character.id,
            stageMouthVisual({
              derived: "speaking",
              participantId: character.id,
              speakerId: asset,
              audioPlayingTurnId,
              currentTurnId: "turn-1",
              mediaRetryNeeded: false,
            }),
          );
        }
      };
      try {
        stage.setCharacters(characters);
        visual(null);
        frame();
        const scene = renderer.render.mock.calls.at(-1)![0] as THREE.Scene;
        const root = scene.getObjectByName(asset)!;
        const seatYaw = standingPlacement(
          characters.find((item) => item.id === asset)!.slot,
        ).yaw;
        expect(root.rotation.y).toBeCloseTo(seatYaw);

        visual("turn-1");
        frame();
        expect(root.rotation.y).toBeCloseTo(seatYaw * Math.exp(-6 * 0.1));
        for (let index = 0; index < 20; index++) frame();
        expect(root.rotation.y).toBeCloseTo(0, 4);
        for (const other of characters.filter((item) => item.id !== asset)) {
          expect(scene.getObjectByName(other.id)!.rotation.y).toBeCloseTo(
            standingPlacement(other.slot).yaw,
          );
        }

        // Audio ends before the server changes its speaking state.
        visual(null);
        frame();
        expect(root.rotation.y).toBeCloseTo(
          seatYaw * (1 - Math.exp(-6 * 0.1)),
          4,
        );
        for (let index = 0; index < 20; index++) frame();
        expect(root.rotation.y).toBeCloseTo(seatYaw, 4);
      } finally {
        stage.dispose();
      }
    },
  );
});
