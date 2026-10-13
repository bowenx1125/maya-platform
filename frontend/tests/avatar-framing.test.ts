import * as THREE from "three";
import {
  GLTFLoader,
  type GLTF,
} from "three/examples/jsm/loaders/GLTFLoader.js";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AvatarRenderer } from "../components/avatar/avatar-renderer";

const renderFrame = vi.hoisted(() => vi.fn());

vi.mock("three", async (importOriginal) => {
  const three = await importOriginal<typeof import("three")>();
  return {
    ...three,
    WebGLRenderer: class {
      setPixelRatio() {}
      setAnimationLoop() {}
      setSize() {}
      dispose() {}
      forceContextLoss() {}
      render = renderFrame;
    },
  };
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  renderFrame.mockClear();
});

describe("avatar scholar framing", () => {
  it.each(["head", "full-body"] as const)(
    "frames the figure without the detached plane in %s view",
    (framing) => {
      const scene = new THREE.Group();
      const body = new THREE.Mesh(
        new THREE.BoxGeometry(1, 2, 0.5),
        new THREE.MeshStandardMaterial(),
      );
      body.name = "Scholar_Body";
      const detached = new THREE.Mesh(
        new THREE.PlaneGeometry(12, 1),
        new THREE.MeshStandardMaterial(),
      );
      detached.name = "aa";
      scene.add(body, detached);
      vi.spyOn(GLTFLoader.prototype, "load").mockImplementation(
        (_url, onLoad) => {
          onLoad({ scene, animations: [] } as unknown as GLTF);
        },
      );
      const requestFrame = vi.fn((_callback: FrameRequestCallback) => 1);
      vi.stubGlobal("requestAnimationFrame", requestFrame);
      vi.stubGlobal("cancelAnimationFrame", vi.fn());
      const renderer = new AvatarRenderer({
        canvas: document.createElement("canvas"),
        assetUrl: "/avatars/elder-scholar.glb",
        framing,
      });
      try {
        expect(detached.visible).toBe(false);
        expect(body.visible).toBe(true);
        const frame = requestFrame.mock
          .calls[0]?.[0] as unknown as FrameRequestCallback;
        frame(performance.now());
        const camera = renderFrame.mock
          .calls[0]?.[1] as THREE.PerspectiveCamera;
        expect(camera.position.z).toBeGreaterThan(5);
        expect(camera.position.z).toBeLessThan(6);
      } finally {
        renderer.dispose();
      }
    },
  );
});
