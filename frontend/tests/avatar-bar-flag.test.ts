import { afterEach, describe, expect, it } from "vitest";

import {
  isDebateAvatarBarEnabled,
  isExperimentalStage3dEnabled,
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

  it("turns on via NEXT_PUBLIC_DEBATE_AVATAR_BAR when URL is silent", () => {
    expect(isDebateAvatarBarEnabled("", "1")).toBe(true);
    expect(resolveDebateStageVisual("", "true")).toBe("avatar-bar");
  });

  it("lets URL avatarBar=0 override a sticky env", () => {
    expect(isDebateAvatarBarEnabled("?avatarBar=0", "1")).toBe(false);
    expect(resolveDebateStageVisual("avatarBar=0", "1")).toBe("scholar3d");
  });

  it("remounts experimental 3D with stage3d=1 while bar flag is on", () => {
    expect(isExperimentalStage3dEnabled("?stage3d=1")).toBe(true);
    expect(resolveDebateStageVisual("?avatarBar=1&stage3d=1", "1")).toBe(
      "scholar3d",
    );
  });
});
