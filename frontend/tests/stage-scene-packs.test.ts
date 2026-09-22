import { describe, expect, it } from "vitest";

import {
  requestedStageScenePack,
  STAGE_SCENE_PACKS,
  stageScenePack,
} from "../components/stage3d/scene-packs";

describe("local stage scene packs", () => {
  it("offers five distinct local splat resources", () => {
    expect(STAGE_SCENE_PACKS).toHaveLength(5);
    expect(new Set(STAGE_SCENE_PACKS.map((pack) => pack.id)).size).toBe(5);
    expect(new Set(STAGE_SCENE_PACKS.map((pack) => pack.splatUrl)).size).toBe(
      5,
    );
  });

  it("falls back safely when a scene query is unknown", () => {
    expect(stageScenePack("missing")).toBe(STAGE_SCENE_PACKS[0]);
    window.history.replaceState(null, "", "/?splat=1&scene=photo");
    expect(requestedStageScenePack().id).toBe("photo");
    window.history.replaceState(null, "", "/");
  });
});
