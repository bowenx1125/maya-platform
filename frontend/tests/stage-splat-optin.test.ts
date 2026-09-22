import { describe, expect, it } from "vitest";

import {
  depthBackdropRequested,
  splatBackdropRequested,
  stageBackdropMode,
  stageCameraTurnSign,
  stageSplatCameraFov,
} from "../components/stage3d/scholar-stage";

describe("stage camera turn direction", () => {
  it("uses positive yaw for left and negative yaw for right", () => {
    expect(stageCameraTurnSign("turn-left")).toBe(1);
    expect(stageCameraTurnSign("turn-right")).toBe(-1);
    expect(stageCameraTurnSign("forward")).toBe(0);
  });
});

describe("responsive splat projection", () => {
  it("widens narrow screens without changing normal desktop framing", () => {
    expect(stageSplatCameraFov(0.46)).toBe(72);
    expect(stageSplatCameraFov(0.7)).toBeGreaterThan(58);
    expect(stageSplatCameraFov(1)).toBe(58);
  });
});

describe("stageBackdropMode", () => {
  it("is off by default and needs exactly splat=1", () => {
    expect(stageBackdropMode()).toBe(null);
    for (const search of [
      "",
      "?splat=true",
      "?splat=0",
      "?SPLAT=1",
      "?splat=1&x=2",
    ]) {
      window.history.replaceState(null, "", `/${search}`);
      expect(stageBackdropMode(), `search=${search}`).toBe(
        search === "?splat=1&x=2" ? "splat" : null,
      );
    }
    window.history.replaceState(null, "", "/");
  });

  it("needs exactly depth=1", () => {
    for (const search of [
      "?depth=true",
      "?depth=0",
      "?DEPTH=1",
      "?depth=1&x=2",
    ]) {
      window.history.replaceState(null, "", `/${search}`);
      expect(stageBackdropMode(), `search=${search}`).toBe(
        search === "?depth=1&x=2" ? "depth" : null,
      );
    }
    window.history.replaceState(null, "", "/");
  });

  it("lets depth win when both flags are present", () => {
    for (const search of ["?depth=1&splat=1", "?splat=1&depth=1"]) {
      window.history.replaceState(null, "", `/${search}`);
      expect(stageBackdropMode(), `search=${search}`).toBe("depth");
    }
    window.history.replaceState(null, "", "/");
  });
});

describe("backdrop request helpers", () => {
  it("map the chosen mode to exactly one loader trigger", () => {
    for (const [search, mode] of [
      ["?splat=1", "splat"],
      ["?depth=1", "depth"],
      ["?depth=1&splat=1", "depth"],
      ["", null],
      ["?depth=2", null],
    ] as const) {
      window.history.replaceState(null, "", `/${search}`);
      expect(depthBackdropRequested(), `depth ${search}`).toBe(
        mode === "depth",
      );
      expect(splatBackdropRequested(), `splat ${search}`).toBe(
        mode === "splat",
      );
    }
    window.history.replaceState(null, "", "/");
  });
});
