import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { afterEach, describe, expect, it, vi } from "vitest";

import { stageMouthVisual } from "../components/debate-beta/stage/mouth-sync";
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

const HUMAN_STAGE_FIGURES = [
  { template_id: "wave1-default-head", url: "/avatars/female_1.glb" },
  { template_id: "maya-warm-scholar", url: "/avatars/elder-scholar.glb" },
  { template_id: "maya-civic-observer", url: "/avatars/noble-scholar.glb" },
] as const;

describe("stage speaking body yaw", () => {
  it.each(HUMAN_STAGE_FIGURES)(
    "$url faces front on live audio and restores its seat yaw afterwards",
    (figure) => {
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
      const characters: StageCharacter[] = HUMAN_STAGE_FIGURES.map(
        (item, index) => ({
          id: item.url,
          slot: (["A", "B", "C"] as const)[index],
          name: item.url,
          config: {
            template_id: item.template_id,
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
              speakerId: figure.url,
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
        const root = scene.getObjectByName(figure.url)!;
        const seatYaw = standingPlacement(
          characters.find((item) => item.id === figure.url)!.slot,
        ).yaw;
        expect(root.rotation.y).toBeCloseTo(seatYaw);

        visual("turn-1");
        frame();
        expect(root.rotation.y).toBeCloseTo(seatYaw * Math.exp(-6 * 0.1));
        for (let index = 0; index < 20; index++) frame();
        expect(root.rotation.y).toBeCloseTo(0, 4);
        for (const other of characters.filter((item) => item.id !== figure.url)) {
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
