import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AvatarRenderer } from "../components/avatar/avatar-renderer";

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
    },
  };
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const emptyScene = {
  asset: { version: "2.0" },
  scene: 0,
  scenes: [{ nodes: [] }],
};

describe("avatar GLB texture loading", () => {
  it("uses the image loader with parser settings without changing other GLTF loaders", async () => {
    const createImageBitmap = vi.fn();
    vi.stubGlobal("createImageBitmap", createImageBitmap);
    const load = vi
      .spyOn(GLTFLoader.prototype, "load")
      .mockImplementation(() => undefined);
    const renderer = new AvatarRenderer({
      canvas: document.createElement("canvas"),
    });
    try {
      const loader = load.mock.contexts[0] as GLTFLoader;
      const manager = new THREE.LoadingManager();
      loader.manager = manager;
      loader.setCrossOrigin("use-credentials");
      loader.setRequestHeader({ "X-Test-Image": "fixture" });
      const { parser } = await loader.parseAsync(
        JSON.stringify(emptyScene),
        "",
      );

      expect(parser.textureLoader).toBeInstanceOf(THREE.TextureLoader);
      expect(parser.textureLoader.manager).toBe(manager);
      expect(parser.textureLoader.crossOrigin).toBe("use-credentials");
      expect(parser.textureLoader.requestHeader).toEqual({
        "X-Test-Image": "fixture",
      });
      const other = await new GLTFLoader().parseAsync(
        JSON.stringify(emptyScene),
        "",
      );
      expect(other.parser.textureLoader).toBeInstanceOf(
        THREE.ImageBitmapLoader,
      );
      expect(globalThis.createImageBitmap).toBe(createImageBitmap);
      expect(createImageBitmap).not.toHaveBeenCalled();
    } finally {
      renderer.dispose();
    }
  });

  it("keeps GLTF orientation and embedded-image URL cleanup on the image path", async () => {
    const createImageBitmap = vi.fn();
    vi.stubGlobal("createImageBitmap", createImageBitmap);
    const fetch = vi.fn(async () => {
      throw new Error("connect-src blocks embedded-image blob fetch");
    });
    vi.stubGlobal("fetch", fetch);
    const createObjectURL = vi.fn(() => "blob:avatar-image-fixture");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal(
      "URL",
      class extends URL {
        static createObjectURL = createObjectURL;
        static revokeObjectURL = revokeObjectURL;
      },
    );
    const load = vi
      .spyOn(GLTFLoader.prototype, "load")
      .mockImplementation(() => undefined);
    const image = document.createElement("img");
    const imageLoad = vi
      .spyOn(THREE.ImageLoader.prototype, "load")
      .mockImplementation((_url, onLoad) => {
        onLoad?.(image);
        return image;
      });
    const renderer = new AvatarRenderer({
      canvas: document.createElement("canvas"),
    });
    try {
      const loader = load.mock.contexts[0] as GLTFLoader;
      const { parser } = await loader.parseAsync(
        JSON.stringify({
          ...emptyScene,
          images: [{ bufferView: 0, mimeType: "image/png" }],
          textures: [{ source: 0 }],
        }),
        "",
      );
      vi.spyOn(parser, "getDependency").mockResolvedValue(new ArrayBuffer(4));
      const texture = await parser.loadTexture(0);

      expect(imageLoad).toHaveBeenCalledWith(
        "blob:avatar-image-fixture",
        expect.any(Function),
        undefined,
        expect.any(Function),
      );
      expect(fetch).not.toHaveBeenCalled();
      expect(texture.image).toBe(image);
      expect(texture.flipY).toBe(false);
      expect(createObjectURL).toHaveBeenCalledOnce();
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:avatar-image-fixture");
      expect(createImageBitmap).not.toHaveBeenCalled();
      texture.dispose();
    } finally {
      renderer.dispose();
    }
  });
});
