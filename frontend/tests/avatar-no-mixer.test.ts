import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import * as pose from "../components/avatar/avatar-pose";
import { describe, expect, it } from "vitest";

const SOURCES = [
  "../components/avatar/avatar-renderer.ts",
  "../components/avatar/avatar-pose.ts",
  "../components/avatar/index.ts",
  "../components/stage3d/scholar-stage.ts",
].map((relative) => fileURLToPath(new URL(relative, import.meta.url)));

describe("avatar idle mixer removal", () => {
  it("leaves no mixer or breath references in avatar sources", () => {
    for (const path of SOURCES) {
      const text = readFileSync(path, "utf8");
      for (const banned of [
        "AnimationMixer",
        "clipAction",
        "applyIdleBreath",
        "selectIdleClip",
      ]) {
        expect(text, `${path} must not contain ${banned}`).not.toContain(
          banned,
        );
      }
    }
  });

  it("no longer exports the breath and idle-clip helpers", () => {
    expect("applyIdleBreath" in pose).toBe(false);
    expect("selectIdleClip" in pose).toBe(false);
    expect("idleBreathAngle" in pose).toBe(false);
  });
});
