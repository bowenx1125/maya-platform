import { afterEach, describe, expect, it } from "vitest";

import {
  isDebateAvatarBarEnabled,
  isExperimentalStage3dEnabled,
  resolveArenaIntensity,
  resolveDebateStageVisual,
} from "../components/stage2d/avatar-bar-flag";

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("avatar-bar flag", () => {
  it("stays off by default so prod keeps ScholarScene", () => {
    expect(isDebateAvatarBarEnabled("", undefined)).toBe(false);
    expect(resolveDebateStageVisual("", undefined)).toBe("scholar3d");
  });

  it("turns on via URL avatarBar=1", () => {
    expect(isDebateAvatarBarEnabled("?avatarBar=1", undefined)).toBe(true);
    expect(resolveDebateStageVisual("avatarBar=1", undefined)).toBe(
      "avatar-bar",
    );
  });

  it("turns on via URL grokBar=1 alias", () => {
    expect(isDebateAvatarBarEnabled("?grokBar=1", undefined)).toBe(true);
    expect(resolveDebateStageVisual("?grokBar=1", undefined)).toBe("avatar-bar");
  });

  it("turns on via NEXT_PUBLIC_DEBATE_AVATAR_BAR when URL is silent", () => {
    expect(isDebateAvatarBarEnabled("", "1")).toBe(true);
    expect(resolveDebateStageVisual("", "true")).toBe("avatar-bar");
  });

  it("lets URL avatarBar=0 override a sticky env", () => {
    expect(isDebateAvatarBarEnabled("?avatarBar=0", "1")).toBe(false);
    expect(resolveDebateStageVisual("avatarBar=0", "1")).toBe("scholar3d");
  });

  it("lets URL grokBar=0 override a sticky env", () => {
    expect(isDebateAvatarBarEnabled("?grokBar=0", "1")).toBe(false);
    expect(resolveDebateStageVisual("?grokBar=0", "1")).toBe("scholar3d");
  });

  it("conflict: any explicit 0 wins over any explicit 1", () => {
    expect(isDebateAvatarBarEnabled("?avatarBar=1&grokBar=0", undefined)).toBe(
      false,
    );
    expect(isDebateAvatarBarEnabled("?avatarBar=0&grokBar=1", undefined)).toBe(
      false,
    );
    expect(resolveDebateStageVisual("?avatarBar=1&grokBar=0", "1")).toBe(
      "scholar3d",
    );
  });

  it("both aliases on without a 0 → on", () => {
    expect(isDebateAvatarBarEnabled("?avatarBar=1&grokBar=1", undefined)).toBe(
      true,
    );
    expect(resolveDebateStageVisual("?avatarBar=1&grokBar=1", undefined)).toBe(
      "avatar-bar",
    );
  });

  it("remounts experimental 3D with stage3d=1 while bar flag is on", () => {
    expect(isExperimentalStage3dEnabled("?stage3d=1")).toBe(true);
    expect(resolveDebateStageVisual("?avatarBar=1&stage3d=1", "1")).toBe(
      "scholar3d",
    );
    expect(resolveDebateStageVisual("?grokBar=1&stage3d=1", undefined)).toBe(
      "scholar3d",
    );
  });

  it("stage3d alone without bar flag does not change prod default", () => {
    expect(resolveDebateStageVisual("?stage3d=1", undefined)).toBe("scholar3d");
  });
});

describe("arena intensity", () => {
  it("defaults to med", () => {
    expect(resolveArenaIntensity("", undefined)).toBe("med");
    expect(resolveArenaIntensity(undefined, undefined)).toBe("med");
  });

  it("reads URL arenaIntensity", () => {
    expect(resolveArenaIntensity("?arenaIntensity=low", undefined)).toBe("low");
    expect(resolveArenaIntensity("arenaIntensity=high", undefined)).toBe(
      "high",
    );
  });

  it("prop wins over URL", () => {
    expect(resolveArenaIntensity("?arenaIntensity=high", "low")).toBe("low");
  });

  it("invalid URL falls back to med", () => {
    expect(resolveArenaIntensity("?arenaIntensity=ultra", undefined)).toBe(
      "med",
    );
  });
});
